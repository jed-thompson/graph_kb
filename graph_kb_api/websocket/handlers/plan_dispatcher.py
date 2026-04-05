"""Plan WebSocket Dispatcher - routes plan.* events to the PlanEngine."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict, cast

from langgraph.types import RunnableConfig
from pydantic import ValidationError

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine
    from graph_kb_api.flows.v3.state.plan_state import ArtifactManifestEntry

from graph_kb_api.context import AppContext, get_app_context
from graph_kb_api.database.base import get_session
from graph_kb_api.database.plan_repositories import PlanSessionRepository
from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import CASCADE_MAP
from graph_kb_api.websocket.events import (
    PhaseId,
    SpecErrorData,
    SpecPhaseProgressData,
    SpecPhasePromptData,
)
from graph_kb_api.websocket.handlers.base import _debug_log, logger
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.plan_events import (
    PlanNavigatePayload,
    PlanPausePayload,
    PlanPhaseInputPayload,
    PlanReconnectPayload,
    PlanResumePayload,
    PlanRetryPayload,
    PlanStartPayload,
    PlanStepForwardPayload,
    emit_error,
    emit_complete,
    set_plan_ws_manager,
)

# ── Types ──────────────────────────────────────────────────────────────


class PlanSession(TypedDict):
    """Typed session dict stored in PlanDispatcher._sessions registry."""

    engine: PlanEngine
    config: RunnableConfig
    session_id: str
    thread_id: str
    user_id: str
    client_id: str
    workflow_id: str
    running_task: Optional[asyncio.Task]


# ── PlanDispatcher ─────────────────────────────────────────────────────


class PlanDispatcher:
    """Routes plan.* WebSocket events to the PlanEngine.

    Owns the session registry, all event handlers, and helper functions
    for emitting events, creating engines, and serializing artifacts.
    """

    _PHASE_ORDER = ("context", "research", "planning", "orchestrate", "assembly")

    def __init__(self) -> None:
        self._sessions: Dict[str, PlanSession] = {}

    # ── Helper methods ─────────────────────────────────────────

    @staticmethod
    def _serialize_plan_artifacts(artifacts: Dict[str, Any]) -> List[ArtifactManifestEntry]:
        """Lazy wrapper for SubgraphAwareNode._serialize_artifacts to avoid circular imports."""

        from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
        return SubgraphAwareNode._serialize_artifacts(artifacts)

    @staticmethod
    def _format_task_research_summary(task_context: Dict[str, Any] | None) -> str | None:
        if not isinstance(task_context, dict):
            return None

        task_research = task_context.get("task_research")
        summary: str | None = None
        key_insights: list[str] = []

        if isinstance(task_research, dict):
            raw_summary = task_research.get("summary")
            if isinstance(raw_summary, str) and raw_summary.strip():
                summary = raw_summary.strip()

            findings = task_research.get("findings")
            if isinstance(findings, dict):
                if not summary:
                    findings_summary = findings.get("summary")
                    if isinstance(findings_summary, str) and findings_summary.strip():
                        summary = findings_summary.strip()

                raw_key_insights = findings.get("key_insights")
                if isinstance(raw_key_insights, list):
                    key_insights = [
                        insight.strip()
                        for insight in raw_key_insights
                        if isinstance(insight, str) and insight.strip()
                    ]

        if not summary:
            research_summary = task_context.get("research_summary")
            if isinstance(research_summary, str) and research_summary.strip():
                summary = research_summary.strip()

        if not summary:
            return None

        if key_insights:
            bullets = "\n".join(f"• {insight}" for insight in key_insights[:5])
            if bullets:
                return f"{summary}\n\n**Key findings:**\n{bullets}"

        return summary

    @classmethod
    def _build_plan_tasks_snapshot(cls, state: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
        if not state:
            return {}

        planning = state.get("plan")
        orchestrate = state.get("orchestrate")
        if not isinstance(orchestrate, dict):
            return {}

        dag_tasks: list[Any] = []
        if isinstance(planning, dict):
            task_dag = planning.get("task_dag")
            if isinstance(task_dag, dict):
                raw_tasks = task_dag.get("tasks")
                if isinstance(raw_tasks, list):
                    dag_tasks = raw_tasks

        plan_tasks: Dict[str, Dict[str, Any]] = {}

        for task in dag_tasks:
            if not isinstance(task, dict):
                continue
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id:
                continue

            dependencies = task.get("dependencies")
            plan_tasks[task_id] = {
                "id": task_id,
                "name": task.get("name") or "Task",
                "status": "pending",
                "priority": task.get("priority") or "medium",
                "dependencies": dependencies if isinstance(dependencies, list) else [],
                "events": [],
                "iterationCount": 0,
                "specSection": task.get("spec_section") if isinstance(task.get("spec_section"), str) else None,
            }

        task_results = orchestrate.get("task_results")
        if isinstance(task_results, list):
            for task_result in task_results:
                if not isinstance(task_result, dict):
                    continue
                task_id = task_result.get("id")
                if not isinstance(task_id, str) or not task_id:
                    continue

                task_entry = plan_tasks.get(task_id, {
                    "id": task_id,
                    "name": task_result.get("name") or task_id,
                    "status": "pending",
                    "priority": "medium",
                    "dependencies": [],
                    "events": [],
                    "iterationCount": 0,
                })

                status = task_result.get("status")
                if status == "done":
                    task_entry["status"] = "complete"
                elif status in {"failed", "error"}:
                    task_entry["status"] = "failed"

                output = task_result.get("output")
                if isinstance(output, str) and output.strip():
                    task_entry["agentContent"] = output

                spec_section = task_result.get("spec_section")
                if isinstance(spec_section, str) and spec_section.strip():
                    task_entry["specSection"] = spec_section

                spec_section_content = task_result.get("spec_section_content")
                if isinstance(spec_section_content, str) and spec_section_content.strip():
                    task_entry["specSectionContent"] = spec_section_content

                research_summary = task_result.get("research_summary")
                if isinstance(research_summary, str) and research_summary.strip():
                    task_entry["researchSummary"] = research_summary

                iteration_count = task_result.get("iteration_count")
                if isinstance(iteration_count, int) and iteration_count > 0:
                    task_entry["iterationCount"] = iteration_count

                plan_tasks[task_id] = task_entry

        current_task = orchestrate.get("current_task")
        current_task_context = orchestrate.get("current_task_context")
        agent_context = orchestrate.get("agent_context")
        critique_feedback = orchestrate.get("critique_feedback")
        critique_passed = orchestrate.get("critique_passed")

        if isinstance(current_task, dict):
            task_id = current_task.get("id")
            if isinstance(task_id, str) and task_id:
                task_entry = plan_tasks.get(task_id, {
                    "id": task_id,
                    "name": current_task.get("name") or task_id,
                    "status": "pending",
                    "priority": current_task.get("priority") or "medium",
                    "dependencies": current_task.get("dependencies") if isinstance(current_task.get("dependencies"), list) else [],
                    "events": [],
                    "iterationCount": 0,
                })

                if task_entry.get("status") not in {"complete", "failed"}:
                    task_entry["status"] = (
                        "critiquing"
                        if isinstance(critique_feedback, str) and critique_feedback.strip() and critique_passed is False
                        else "in_progress"
                    )

                spec_section = current_task.get("spec_section")
                if isinstance(spec_section, str) and spec_section.strip():
                    task_entry["specSection"] = spec_section

                if isinstance(agent_context, dict):
                    spec_section_content = agent_context.get("spec_section_content")
                    if isinstance(spec_section_content, str) and spec_section_content.strip():
                        task_entry["specSectionContent"] = spec_section_content

                research_summary = cls._format_task_research_summary(
                    current_task_context if isinstance(current_task_context, dict) else None
                )
                if research_summary:
                    task_entry["researchSummary"] = research_summary

                iteration_count = orchestrate.get("iteration_count")
                if isinstance(iteration_count, int) and iteration_count > 0:
                    task_entry["iterationCount"] = max(
                        int(task_entry.get("iterationCount") or 0),
                        iteration_count,
                    )

                current_draft = orchestrate.get("current_draft")
                if (
                    isinstance(current_draft, str)
                    and current_draft.strip()
                    and not isinstance(task_entry.get("agentContent"), str)
                ):
                    task_entry["agentContent"] = current_draft

                plan_tasks[task_id] = task_entry

        return plan_tasks

    @staticmethod
    def _serialize_document_manifest(document_manifest: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not isinstance(document_manifest, dict):
            return None

        entries_payload: list[Dict[str, Any]] = []
        entries = document_manifest.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                artifact_ref = entry.get("artifact_ref")
                download_url = artifact_ref.get("key") if isinstance(artifact_ref, dict) else ""
                filename = ""
                if isinstance(download_url, str) and download_url:
                    filename = download_url.split("/")[-1]

                entries_payload.append(
                    {
                        "taskId": entry.get("task_id", ""),
                        "specSection": entry.get("spec_section", ""),
                        "downloadUrl": download_url if isinstance(download_url, str) else "",
                        "status": entry.get("status", "draft"),
                        "tokenCount": entry.get("token_count", 0),
                        "filename": filename,
                        "sectionType": entry.get("section_type"),
                        "errorMessage": entry.get("error_message"),
                    }
                )

        composed_index_ref = document_manifest.get("composed_index_ref")
        composed_index_url = composed_index_ref.get("key") if isinstance(composed_index_ref, dict) else ""

        return {
            "specName": document_manifest.get("spec_name", "Untitled"),
            "totalDocuments": document_manifest.get("total_documents", len(entries_payload)),
            "totalTokens": document_manifest.get("total_tokens", 0),
            "composedIndexUrl": composed_index_url if isinstance(composed_index_url, str) else "",
            "entries": entries_payload,
        }

    @classmethod
    def _build_active_task_context_snapshot(cls, state: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not state:
            return None

        orchestrate = state.get("orchestrate")
        if not isinstance(orchestrate, dict):
            return None

        current_task = orchestrate.get("current_task")
        current_task_context = orchestrate.get("current_task_context")
        agent_context = orchestrate.get("agent_context")

        task_id = current_task.get("id") if isinstance(current_task, dict) else None
        task_name = current_task.get("name") if isinstance(current_task, dict) else None
        spec_section = current_task.get("spec_section") if isinstance(current_task, dict) else None
        spec_section_content = agent_context.get("spec_section_content") if isinstance(agent_context, dict) else None
        research_summary = cls._format_task_research_summary(
            current_task_context if isinstance(current_task_context, dict) else None
        )

        if not any([
            isinstance(task_id, str) and task_id,
            isinstance(spec_section, str) and spec_section,
            isinstance(spec_section_content, str) and spec_section_content,
            isinstance(research_summary, str) and research_summary,
        ]):
            return None

        return {
            "task_id": task_id if isinstance(task_id, str) and task_id else None,
            "task_name": task_name if isinstance(task_name, str) and task_name else None,
            "spec_section": spec_section if isinstance(spec_section, str) and spec_section else None,
            "spec_section_content": (
                spec_section_content
                if isinstance(spec_section_content, str) and spec_section_content
                else None
            ),
            "research_summary": research_summary,
        }

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return value

    @classmethod
    def _build_context_items_snapshot(cls, state: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not state:
            return None

        context = state.get("context")
        if not isinstance(context, dict):
            return None

        snapshot: Dict[str, Any] = {}
        for key in (
            "extracted_urls",
            "rounds",
            "primary_document_id",
            "supporting_doc_ids",
            "user_explanation",
        ):
            value = context.get(key)
            if value not in (None, "", [], {}):
                snapshot[key] = cls._to_jsonable(value)

        return snapshot or None

    @classmethod
    def _build_phase_results_snapshot(cls, state: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
        if not state:
            return {}

        phase_results: Dict[str, Dict[str, Any]] = {}
        context = state.get("context")
        review = state.get("review")
        research = state.get("research")
        planning = state.get("plan")
        orchestrate = state.get("orchestrate")
        completeness = state.get("completeness")
        generate = state.get("generate")

        if isinstance(context, dict) or isinstance(review, dict):
            context_result: Dict[str, Any] = {}
            if isinstance(context, dict):
                for key in ("spec_name", "user_explanation", "constraints", "summary", "deep_analysis"):
                    value = context.get(key)
                    if value not in (None, "", [], {}):
                        context_result[key] = cls._to_jsonable(value)
            if isinstance(review, dict):
                for key in (
                    "summary",
                    "analysis",
                    "gaps",
                    "clarification_questions",
                    "suggested_actions",
                    "completeness_score",
                    "approved",
                ):
                    value = review.get(key)
                    if value not in (None, "", [], {}):
                        context_result[key] = cls._to_jsonable(value)
            if context_result:
                phase_results["context"] = context_result

        if isinstance(research, dict) and research:
            research_result: Dict[str, Any] = {}
            for key in (
                "findings",
                "gaps",
                "confidence_score",
                "confidence_sufficient",
                "research_gap_iterations",
                "approved",
                "approval_decision",
                "approval_feedback",
                "review_feedback",
                "findings_doc_id",
            ):
                value = research.get(key)
                if value not in (None, "", [], {}):
                    research_result[key] = cls._to_jsonable(value)
            if research_result:
                phase_results["research"] = research_result

        if isinstance(planning, dict) and planning:
            planning_result: Dict[str, Any] = {}
            for key in (
                "roadmap",
                "feasibility",
                "task_dag",
                "validation",
                "alignment",
                "approved",
                "approval_decision",
                "approval_feedback",
                "needs_revision",
            ):
                value = planning.get(key)
                if value not in (None, "", [], {}):
                    planning_result[key] = cls._to_jsonable(value)
            if planning_result:
                phase_results["planning"] = planning_result

        plan_tasks = cls._build_plan_tasks_snapshot(state)
        if isinstance(orchestrate, dict) and (orchestrate or plan_tasks):
            orchestrate_result: Dict[str, Any] = {}
            total_tasks = len(plan_tasks)
            completed_tasks = len(
                [task for task in plan_tasks.values() if task.get("status") == "complete"]
            )
            failed_tasks = len(
                [task for task in plan_tasks.values() if task.get("status") == "failed"]
            )
            if total_tasks:
                orchestrate_result.update(
                    {
                        "summary": f"{completed_tasks} of {total_tasks} tasks completed",
                        "total_tasks": total_tasks,
                        "completed_tasks": completed_tasks,
                        "failed_tasks": failed_tasks,
                    }
                )
            for key in ("all_complete", "iteration_count", "critique_feedback", "critique_passed"):
                value = orchestrate.get(key)
                if value not in (None, "", [], {}):
                    orchestrate_result[key] = cls._to_jsonable(value)
            if orchestrate_result:
                phase_results["orchestrate"] = orchestrate_result

        if isinstance(completeness, dict) or isinstance(generate, dict):
            assembly_result: Dict[str, Any] = {}
            validation = completeness.get("validation") if isinstance(completeness, dict) else None
            spec_name = ""
            context_data = state.get("context")
            if isinstance(context_data, dict):
                spec_name = str(context_data.get("spec_name") or "")
            spec_document_path = ""
            if isinstance(generate, dict):
                raw_path = generate.get("spec_document_path")
                if isinstance(raw_path, str) and raw_path:
                    spec_document_path = raw_path
            sections_generated = 0
            document_manifest = cls._serialize_document_manifest(
                state.get("document_manifest") if isinstance(state.get("document_manifest"), dict) else None
            )
            if document_manifest:
                sections_generated = int(document_manifest.get("totalDocuments", 0) or 0)
                assembly_result["document_manifest"] = document_manifest
            elif isinstance(generate, dict):
                sections = generate.get("sections")
                if isinstance(sections, dict):
                    sections_generated = len(sections)

            summary_parts: list[str] = []
            if spec_name:
                summary_parts.append(spec_name)
            if sections_generated:
                summary_parts.append(f"{sections_generated} sections generated")
            if isinstance(validation, dict):
                warnings = validation.get("warnings")
                errors = validation.get("errors")
                warning_count = len(warnings) if isinstance(warnings, list) else 0
                error_count = len(errors) if isinstance(errors, list) else 0
                summary_parts.append(f"{error_count} errors")
                summary_parts.append(f"{warning_count} warnings")
            if summary_parts:
                assembly_result["summary"] = " | ".join(summary_parts)

            for key in ("approved", "approval_decision", "approval_feedback", "consistency_issues"):
                value = completeness.get(key) if isinstance(completeness, dict) else None
                if value not in (None, "", [], {}):
                    assembly_result[key] = cls._to_jsonable(value)
            if isinstance(validation, dict) and validation:
                assembly_result["validation"] = cls._to_jsonable(validation)
            if spec_document_path:
                assembly_result["spec_document_path"] = spec_document_path
            if sections_generated:
                assembly_result["sections_generated"] = sections_generated
            if assembly_result:
                phase_results["assembly"] = assembly_result

        return phase_results

    @classmethod
    def _build_plan_state_payload(
        cls,
        *,
        session_id: str,
        state: Dict[str, Any] | None,
        workflow_status: str | None = None,
        completed_phases: Dict[str, bool] | None = None,
        current_phase: str | None = None,
        budget: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        resolved_state = state or {}
        resolved_completed = completed_phases or cls._normalize_completed_phases(resolved_state)
        resolved_current_phase = current_phase or cls._resolve_current_phase(resolved_state)
        resolved_budget = budget or cast(Dict[str, Any], resolved_state.get("budget", {}) or {})
        raw_workflow_status = workflow_status or resolved_state.get("workflow_status")
        resolved_workflow_status = raw_workflow_status if isinstance(raw_workflow_status, str) and raw_workflow_status else "running"

        payload: Dict[str, Any] = {
            "session_id": session_id,
            "current_phase": resolved_current_phase,
            "completed_phases": resolved_completed,
            "workflow_status": resolved_workflow_status,
            "budget": {
                "remainingLlmCalls": resolved_budget.get("remaining_llm_calls", 0),
                "tokensUsed": resolved_budget.get("tokens_used", 0),
                "maxLlmCalls": resolved_budget.get("max_llm_calls", 200),
                "maxTokens": resolved_budget.get("max_tokens", 500_000),
            },
            "artifacts": cls._serialize_plan_artifacts(resolved_state.get("artifacts", {})),
        }

        document_manifest = cls._serialize_document_manifest(
            resolved_state.get("document_manifest")
            if isinstance(resolved_state.get("document_manifest"), dict)
            else None
        )
        if document_manifest:
            payload["document_manifest"] = document_manifest

        plan_tasks = cls._build_plan_tasks_snapshot(resolved_state)
        if plan_tasks:
            payload["plan_tasks"] = plan_tasks

        active_task_context = cls._build_active_task_context_snapshot(resolved_state)
        if active_task_context:
            payload["task_context"] = active_task_context

        context_items = cls._build_context_items_snapshot(resolved_state)
        if context_items:
            payload["context_items"] = context_items

        phase_results = cls._build_phase_results_snapshot(resolved_state)
        if phase_results:
            payload["phase_results"] = phase_results

        return payload

    @staticmethod
    async def _persist_session_to_db(
        session_id: str,
        thread_id: str | None,
        user_id: str | None,
        workflow_status: str = "running",
        current_phase: str | None = None,
        completed_phases: dict | None = None,
        fingerprints: dict | None = None,
        budget_state: dict | None = None,
        context_items: dict | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Persist plan session metadata to DB (fire-and-forget).

        Creates the row on first call, updates on subsequent calls.
        Silently drops errors so the workflow is never blocked by DB issues.
        """
        try:
            async with get_session() as db:
                repo = PlanSessionRepository(db)
                existing = await repo.get(session_id)
                if existing:
                    update_fields: Dict[str, Any] = {
                        "workflow_status": workflow_status,
                    }
                    if current_phase is not None:
                        update_fields["current_phase"] = current_phase
                    if completed_phases is not None:
                        update_fields["completed_phases"] = completed_phases
                    if fingerprints is not None:
                        update_fields["fingerprints"] = fingerprints
                    if budget_state is not None:
                        update_fields["budget_state"] = budget_state
                    if context_items is not None:
                        update_fields["context_items"] = context_items
                    await repo.update(
                        session_id,
                        **update_fields,
                    )
                else:
                    if not thread_id or not user_id:
                        logger.warning(
                            "Skipping plan session create without thread_id/user_id",
                            extra={"session_id": session_id},
                        )
                        return
                    await repo.create(
                        session_id=session_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        name=name,
                        description=description,
                    )
                    await repo.update(
                        session_id,
                        workflow_status=workflow_status,
                        current_phase=current_phase or "context",
                        completed_phases=completed_phases or {},
                        fingerprints=fingerprints or {},
                        budget_state=budget_state or {},
                        context_items=context_items or {},
                    )
        except Exception:
            logger.warning("Failed to persist plan session to DB", exc_info=True)

    @classmethod
    def _infer_completed_phases(cls, current_phase: str | None) -> dict[str, bool]:
        completed: dict[str, bool] = {}

        if not current_phase or current_phase not in cls._PHASE_ORDER:
            return completed

        current_index = cls._PHASE_ORDER.index(current_phase)
        for phase in cls._PHASE_ORDER[:current_index]:
            completed[phase] = True

        return completed

    @staticmethod
    def _artifacts_include_prefix(state: Dict[str, Any] | None, *prefixes: str) -> bool:
        if not state:
            return False

        artifacts = state.get("artifacts")
        if not isinstance(artifacts, dict):
            return False

        for key in artifacts.keys():
            if isinstance(key, str) and any(key.startswith(prefix) for prefix in prefixes):
                return True

        return False

    @staticmethod
    def _phase_dict_has_data(state: Dict[str, Any] | None, phase_key: str) -> bool:
        if not state:
            return False

        phase_state = state.get(phase_key)
        return isinstance(phase_state, dict) and bool(phase_state)

    @classmethod
    def _phase_approved(cls, state: Dict[str, Any] | None, phase_key: str) -> bool:
        if not cls._phase_dict_has_data(state, phase_key):
            return False

        phase_state = state.get(phase_key, {})
        return phase_state.get("approved") is True or phase_state.get("approval_decision") == "approve"

    @classmethod
    def _has_research_progress(cls, state: Dict[str, Any] | None) -> bool:
        return cls._phase_dict_has_data(state, "research") or cls._artifacts_include_prefix(state, "research.")

    @classmethod
    def _has_planning_progress(cls, state: Dict[str, Any] | None) -> bool:
        return cls._phase_dict_has_data(state, "plan") or cls._artifacts_include_prefix(
            state,
            "plan.",
            "planning.",
        )

    @classmethod
    def _has_orchestrate_progress(cls, state: Dict[str, Any] | None) -> bool:
        return cls._phase_dict_has_data(state, "orchestrate") or cls._artifacts_include_prefix(
            state,
            "orchestrate.",
        )

    @classmethod
    def _has_assembly_progress(cls, state: Dict[str, Any] | None) -> bool:
        if not state:
            return False

        current_phase = state.get("current_phase")
        if isinstance(current_phase, str) and current_phase == "assembly":
            return True

        completeness = state.get("completeness")
        if isinstance(completeness, dict) and completeness:
            return True

        generate_state = state.get("generate")
        if isinstance(generate_state, dict) and generate_state:
            return True

        artifacts = state.get("artifacts")
        if isinstance(artifacts, dict):
            for key in artifacts.keys():
                if isinstance(key, str) and (
                    key.startswith("assembly.")
                    or key.startswith("generate.")
                ):
                    return True

        return False

    @classmethod
    def _normalize_completed_phases(
        cls,
        state: Dict[str, Any] | None,
        fallback_phase: str | None = None,
    ) -> dict[str, bool]:
        completed = dict((state or {}).get("completed_phases", {}) or {})
        current_phase = (state or {}).get("current_phase")
        effective_phase: str | None = None

        if isinstance(current_phase, str) and current_phase in cls._PHASE_ORDER:
            effective_phase = current_phase
        elif fallback_phase in cls._PHASE_ORDER:
            effective_phase = fallback_phase

        if effective_phase:
            completed.update(cls._infer_completed_phases(effective_phase))

        if cls._has_research_progress(state):
            completed.update(cls._infer_completed_phases("research"))
        if cls._phase_approved(state, "research"):
            completed["research"] = True

        if cls._has_planning_progress(state):
            completed.update(cls._infer_completed_phases("planning"))
        if cls._phase_approved(state, "plan"):
            completed["planning"] = True

        if cls._has_orchestrate_progress(state):
            completed.update(cls._infer_completed_phases("orchestrate"))

        orchestrate_state = (state or {}).get("orchestrate")
        if isinstance(orchestrate_state, dict) and orchestrate_state.get("all_complete") is True:
            completed["orchestrate"] = True

        if cls._has_assembly_progress(state):
            completed.update(cls._infer_completed_phases("assembly"))

        return completed

    @classmethod
    def _resolve_current_phase(
        cls,
        state: Dict[str, Any] | None,
        fallback_phase: str | None = None,
    ) -> str:
        completed = cls._normalize_completed_phases(state, fallback_phase=fallback_phase)

        for phase in cls._PHASE_ORDER:
            if not completed.get(phase):
                return phase

        return "assembly"

    @staticmethod
    def _merge_runtime_state(
        state: Dict[str, Any] | None,
        result: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        """Merge checkpoint state with the latest graph result.

        LangGraph checkpoints can lag the immediate ``ainvoke`` return value for
        terminal transitions, especially when a subgraph reaches END and the
        parent graph finalizes in the same resume cycle. Prefer the latest
        result for persistence so completed/rejected/error terminal states are
        durably reflected in the plan session row.
        """
        merged: Dict[str, Any] = dict(state or {})
        if not result:
            return merged

        shallow_merge_keys = {
            "artifacts",
            "budget",
            "context",
            "review",
            "research",
            "plan",
            "orchestrate",
            "completeness",
            "generate",
            "completed_phases",
            "fingerprints",
            "error",
        }

        for key, value in result.items():
            if value is None:
                continue
            if (
                key in shallow_merge_keys
                and isinstance(merged.get(key), dict)
                and isinstance(value, dict)
            ):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value

        return merged

    @staticmethod
    def _is_terminal_status(workflow_status: str | None) -> bool:
        return workflow_status in {"completed", "error", "rejected"}

    @staticmethod
    def _get_interrupt_option_ids(interrupt_data: Dict[str, Any] | None) -> set[str]:
        if not interrupt_data:
            return set()
        options = interrupt_data.get("options")
        if not isinstance(options, list):
            return set()
        option_ids: set[str] = set()
        for option in options:
            if isinstance(option, dict) and isinstance(option.get("id"), str):
                option_ids.add(option["id"])
        return option_ids

    @classmethod
    def _resolve_failed_phase(cls, state: Dict[str, Any] | None, fallback_phase: str | None = None) -> str:
        completed = cls._normalize_completed_phases(state, fallback_phase=fallback_phase)
        for phase in cls._PHASE_ORDER:
            if not completed.get(phase):
                return phase
        if fallback_phase:
            return fallback_phase
        return cls._resolve_current_phase(state or {})

    @classmethod
    def _is_budget_interrupt(cls, interrupt_data: Dict[str, Any] | None) -> bool:
        option_ids = cls._get_interrupt_option_ids(interrupt_data)
        return "increase_budget" in option_ids

    @staticmethod
    def _resolve_spec_document_url(state: Dict[str, Any] | None) -> str:
        if not state:
            return ""

        manifest = state.get("document_manifest")
        if isinstance(manifest, dict):
            composed_index_ref = manifest.get("composed_index_ref")
            if isinstance(composed_index_ref, dict):
                key = composed_index_ref.get("key")
                if isinstance(key, str) and key:
                    return key

        generate_state = state.get("generate")
        if isinstance(generate_state, dict):
            spec_document_url = generate_state.get("spec_document_path")
            if isinstance(spec_document_url, str) and spec_document_url:
                return spec_document_url

        return ""

    @classmethod
    def _has_document_output(cls, state: Dict[str, Any] | None) -> bool:
        if not state:
            return False

        if cls._resolve_spec_document_url(state):
            return True

        manifest = state.get("document_manifest")
        if isinstance(manifest, dict):
            entries = manifest.get("entries")
            if isinstance(entries, list) and len(entries) > 0:
                return True

        return False

    @classmethod
    async def _emit_terminal_status_if_needed(
        cls,
        *,
        state: Dict[str, Any] | None,
        result: Dict[str, Any] | None,
        client_id: str,
        workflow_id: str,
        session_id: str,
        fallback_phase: str | None = None,
    ) -> bool:
        merged_state = cls._merge_runtime_state(state, result)
        workflow_status = merged_state.get("workflow_status")

        if workflow_status != "error":
            return False

        error_info = merged_state.get("error")
        if not isinstance(error_info, dict):
            error_info = {}

        phase_str = error_info.get("phase")
        if not isinstance(phase_str, str) or not phase_str:
            phase_str = cls._resolve_failed_phase(merged_state, fallback_phase)

        error_message = error_info.get("message")
        if not isinstance(error_message, str) or not error_message:
            error_message = f"{phase_str} phase ended without completing"

        error_code = error_info.get("code")
        if not isinstance(error_code, str) or not error_code:
            error_code = "PHASE_INCOMPLETE"

        phase_enum: Optional[PhaseId] = None
        try:
            phase_enum = PhaseId(phase_str)
        except ValueError:
            phase_enum = None

        await cls._emit_plan_error(
            client_id=client_id,
            workflow_id=workflow_id,
            message=error_message,
            code=error_code,
            phase=phase_enum,
        )
        return True

    @classmethod
    async def _recover_stale_terminal_completion(
        cls,
        *,
        session_id: str,
        thread_id: str,
        user_id: str,
        client_id: str,
        workflow_id: str,
        engine: PlanEngine,
        config: RunnableConfig,
        state: Dict[str, Any] | None,
        result: Dict[str, Any] | None = None,
    ) -> bool:
        merged_state = cls._merge_runtime_state(state, result)
        workflow_status = merged_state.get("workflow_status")
        if workflow_status == "completed":
            return False

        completed_phases = merged_state.get("completed_phases", {}) or {}
        completeness = merged_state.get("completeness", {}) or {}
        approval_decision = completeness.get("approval_decision")
        is_approved = completeness.get("approved") is True or approval_decision == "approve"

        if (
            not completed_phases.get("assembly")
            or approval_decision == "reject"
            or not is_approved
            or not cls._has_document_output(merged_state)
        ):
            return False

        spec_document_url = cls._resolve_spec_document_url(merged_state)
        manifest = merged_state.get("document_manifest")

        try:
            await engine.workflow.aupdate_state(config, {"workflow_status": "completed"})
        except Exception:
            logger.warning("Failed to update stale completed workflow status", exc_info=True)

        await cls._persist_runtime_snapshot(
            session_id,
            thread_id,
            user_id,
            engine,
            config,
            workflow_status="completed",
            result={**merged_state, "workflow_status": "completed"},
        )

        await emit_complete(
            session_id=session_id,
            document_manifest=manifest if isinstance(manifest, dict) else None,
            spec_document_url=spec_document_url,
            client_id=client_id,
        )
        logger.warning(
            "Recovered stale completed plan session before terminal prompt handling",
            extra={"session_id": session_id, "workflow_id": workflow_id},
        )
        return True

    @classmethod
    async def _persist_runtime_snapshot(
        cls,
        session_id: str,
        thread_id: str,
        user_id: str,
        engine: PlanEngine,
        config: RunnableConfig,
        *,
        fallback_phase: str | None = None,
        workflow_status: str | None = None,
        result: Dict[str, Any] | None = None,
    ) -> None:
        try:
            state = await engine.get_workflow_state(config)
            if state is None:
                merged_state = cls._merge_runtime_state(None, result)
                normalized_completed = cls._normalize_completed_phases(
                    merged_state,
                    fallback_phase=fallback_phase,
                )
                await cls._persist_session_to_db(
                    session_id=session_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    workflow_status=workflow_status or merged_state.get("workflow_status") or "running",
                    current_phase=cls._resolve_current_phase(
                        merged_state,
                        fallback_phase=fallback_phase,
                    )
                    if merged_state
                    else fallback_phase,
                    completed_phases=normalized_completed,
                    fingerprints=merged_state.get("fingerprints"),
                    budget_state=merged_state.get("budget"),
                    context_items=merged_state.get("context"),
                )
                return

            merged_state = cls._merge_runtime_state(state, result)
            normalized_completed = cls._normalize_completed_phases(
                merged_state,
                fallback_phase=fallback_phase,
            )
            await cls._persist_session_to_db(
                session_id=session_id,
                thread_id=thread_id,
                user_id=user_id,
                workflow_status=workflow_status or merged_state.get("workflow_status") or "running",
                current_phase=cls._resolve_current_phase(
                    merged_state,
                    fallback_phase=fallback_phase,
                ),
                completed_phases=normalized_completed,
                fingerprints=merged_state.get("fingerprints"),
                budget_state=merged_state.get("budget"),
                context_items=merged_state.get("context"),
            )
        except Exception:
            logger.warning("Failed to persist runtime snapshot for plan session", exc_info=True)

    @staticmethod
    async def _emit_plan_error(
        client_id: str,
        workflow_id: str,
        message: str,
        code: str,
        phase: Optional[PhaseId] = None,
    ) -> None:
        """Emit a plan.error event (fire-and-forget).

        Silently drops the event if the WebSocket client has disconnected (Req 29.2).
        """
        try:
            error_data = SpecErrorData(message=message, code=code, phase=phase)
            await manager.send_event(
                client_id=client_id,
                event_type="plan.error",
                workflow_id=workflow_id,
                data=error_data.model_dump(),
            )
            logger.warning(
                "plan.error emitted to client: phase=%s, code=%s, message=%s",
                phase,
                code,
                message,
            )
        except Exception:
            logger.warning("Failed to emit plan error (client may have disconnected): %s", message)

    @staticmethod
    async def _emit_phase_prompt(client_id: str, workflow_id: str, prompt_data: Dict[str, Any]) -> None:
        """Emit a plan.phase.prompt event (fire-and-forget).

        Handles three prompt types:
        - context-style prompts (with ``fields``) - form inputs
        - approval-style prompts (with ``options``) - approve/reject decisions
        - phase_review prompts (with ``result`` + ``next_phase``) - phase completion review

        Approval and phase_review interrupts preserve their extra keys so the frontend
        can render rich forms.  Form-style interrupts pass through their ``fields`` directly.

        Silently drops the event if the WebSocket client has disconnected (Req 29.2).
        """
        try:
            data = dict(prompt_data)
            session_id = data.get("session_id")
            phase_name = data.get("phase")
            interrupt_id = data.pop("_interrupt_id", None)
            task_id = data.pop("_task_id", None)
            for key in [key for key in list(data.keys()) if key.startswith("_")]:
                data.pop(key, None)
            is_approval = data.get("type") == "approval"
            is_phase_review = data.get("type") == "phase_review"
            is_analysis_review = data.get("type") == "analysis_review"

            # Stash type-specific keys before we touch the dict.
            # context_items, artifacts, and budget are preserved for ALL prompt
            # types so the frontend Gathered Context panel works across phases.
            type_extras: Dict[str, Any] = {}
            # Universal keys — always carry these through
            for key in ("context_items", "artifacts", "budget"):
                if key in data:
                    type_extras[key] = data.pop(key)
            if is_approval:
                for key in ("type", "summary", "message", "options", "tasks"):
                    if key in data:
                        type_extras[key] = data[key]
            elif is_phase_review:
                # Phase review needs: type, result, next_phase, message, options
                for key in ("type", "result", "next_phase", "message", "options"):
                    if key in data:
                        type_extras[key] = data[key]
            elif is_analysis_review:
                for key in (
                    "type",
                    "completeness_score",
                    "gaps",
                    "clarification_questions",
                    "suggested_actions",
                    "architecture_analysis",
                    "message",
                ):
                    if key in data:
                        type_extras[key] = data[key]

            # Ensure fields list exists for serialization
            if "fields" not in data:
                if is_approval:
                    # Build minimal fallback fields so SpecPhasePromptData validates
                    options_raw = data.get("options", [])
                    data["fields"] = [
                        {
                            "id": "decision",
                            "label": data.get("message", "Approve?"),
                            "type": "select",
                            "required": True,
                            "options": [opt["id"] if isinstance(opt, dict) else str(opt) for opt in options_raw],
                        },
                        {
                            "id": "feedback",
                            "label": "Feedback (optional)",
                            "type": "textarea",
                            "required": False,
                            "placeholder": "Any feedback or notes...",
                        },
                    ]
                    if options_raw:
                        data.setdefault("prefilled", {})["decision"] = (
                            options_raw[0]["id"] if isinstance(options_raw[0], dict) else str(options_raw[0])
                        )
                else:
                    data["fields"] = []

            # Build agent_content from summary/message if present
            summary = data.get("summary")
            message = data.get("message")
            if summary is not None or message is not None:
                parts: list[str] = []
                if message:
                    parts.append(str(message))
                if isinstance(summary, dict):
                    for k, v in summary.items():
                        parts.append(f"- **{k}**: {v}")
                elif summary is not None:
                    parts.append(str(summary))
                data["agent_content"] = "\n".join(parts)

            # Remove keys that SpecPhasePromptData doesn't accept
            for key in ("step", "type", "options", "summary", "message"):
                data.pop(key, None)

            serialized = SpecPhasePromptData(**data).model_dump()

            # Merge back type-specific keys so the frontend can detect type
            if type_extras:
                serialized.update(type_extras)
            if isinstance(interrupt_id, str) and interrupt_id:
                serialized["interrupt_id"] = interrupt_id
            if isinstance(task_id, str) and task_id:
                serialized["task_id"] = task_id

            logger.info(
                "_emit_phase_prompt: sending plan.phase.prompt event phase=%s type=%s",
                data.get("phase"),
                type_extras.get("type"),
            )
            await manager.send_event(
                client_id=client_id,
                event_type="plan.phase.prompt",
                workflow_id=workflow_id,
                data=serialized,
            )
            if isinstance(session_id, str) and session_id:
                persisted_phase = phase_name if isinstance(phase_name, str) and phase_name else None
                await PlanDispatcher._persist_session_to_db(
                    session_id=session_id,
                    thread_id=None,
                    user_id=None,
                    workflow_status="paused",
                    current_phase=persisted_phase,
                    completed_phases=(
                        PlanDispatcher._infer_completed_phases(persisted_phase)
                        if persisted_phase
                        else None
                    ),
                )
            logger.info("_emit_phase_prompt: send_event complete for plan.phase.prompt")
        except Exception as exc:
            logger.warning("Failed to emit plan.phase.prompt: %s", exc, exc_info=True)
            # fire-and-forget pattern (Req 29.2)

    @staticmethod
    async def _emit_phase_progress(client_id: str, workflow_id: str, progress_data: Dict[str, Any]) -> None:
        """Emit a plan.phase.progress event (fire-and-forget).

        Silently drops the event if the WebSocket client has disconnected,
        ensuring the workflow continues uninterrupted (Req 29.1, 29.2).
        """
        try:
            # Clamp percent to valid range before validation
            if "percent" in progress_data:
                progress_data["percent"] = max(0.0, min(1.0, progress_data["percent"]))
            serialized = SpecPhaseProgressData(**progress_data)
            await manager.send_event(
                client_id=client_id,
                event_type="plan.phase.progress",
                workflow_id=workflow_id,
                data=serialized.model_dump(),
            )
        except Exception:
            # Silently drop — fire-and-forget pattern (Req 29.2)
            pass

    @staticmethod
    async def _check_and_emit_error(result: Dict[str, Any], client_id: str, workflow_id: str, session_id: str) -> bool:
        """Check result for error and emit plan.error. Returns True if found."""
        error_info = result.get("error")
        if not error_info:
            return False

        # Filter out empty dicts (set by _update_state_with_result when clearing errors)
        if isinstance(error_info, dict) and not error_info.get("message"):
            return False

        phase_str = error_info.get("phase")
        phase_enum: Optional[PhaseId] = None
        if phase_str:
            try:
                phase_enum = PhaseId(phase_str)
            except ValueError:
                pass

        error_message = error_info.get("message", "Phase execution failed")
        error_code = error_info.get("code", "PHASE_EXECUTION_ERROR")

        logger.warning(
            "Plan error detected in workflow result: phase=%s, code=%s, message=%s, error_info=%s",
            phase_str,
            error_code,
            error_message,
            error_info,
            extra={"session_id": session_id},
        )

        await PlanDispatcher._emit_plan_error(
            client_id=client_id,
            workflow_id=workflow_id,
            message=error_message,
            code=error_code,
            phase=phase_enum,
        )
        return True

    @classmethod
    async def _extract_interrupt_from_state(
        cls,
        engine: PlanEngine,
        config: RunnableConfig,
        preferred_phase: str | None = None,
        interrupt_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Extract interrupt payload from the current state checkpoint snapshot.

        Handles both flat graphs and nested subgraphs by recursively checking
        tasks for interrupt payloads.
        """
        try:
            snapshot = await engine.compiled_workflow.aget_state(config)
            if not snapshot:
                logger.debug("_extract_interrupt_from_state: no snapshot")
                return None

            snapshot_values = snapshot.values or {}
            resolved_phase = preferred_phase
            if not resolved_phase:
                current_phase = snapshot_values.get("current_phase")
                if isinstance(current_phase, str) and current_phase:
                    resolved_phase = current_phase
                else:
                    resolved_phase = cls._resolve_current_phase(snapshot_values)

            logger.debug(
                "_extract_interrupt_from_state: next=%s, tasks_count=%s, preferred_phase=%s",
                snapshot.next,
                len(snapshot.tasks) if snapshot.tasks else 0,
                resolved_phase,
            )

            if not snapshot.tasks:
                return None

            def _extract_candidates(tasks: list[Any]) -> list[dict[str, Any]]:
                candidates: list[dict[str, Any]] = []
                for i, task in enumerate(tasks):
                    interrupts = getattr(task, "interrupts", None)
                    logger.debug(
                        "_extract_interrupt_from_state: task[%d] name=%s interrupts=%s",
                        i,
                        getattr(task, "name", "?"),
                        interrupts,
                    )
                    if not interrupts:
                        continue

                    if isinstance(interrupts, (list, tuple)):
                        for j, obj in enumerate(interrupts):
                            val = getattr(obj, "value", obj if isinstance(obj, dict) else None)
                            if isinstance(val, dict):
                                interrupt_payload = dict(val)
                                interrupt_payload["_interrupt_id"] = getattr(obj, "id", None)
                                interrupt_payload["_task_id"] = getattr(task, "id", None)
                                candidates.append(
                                    {
                                        "value": interrupt_payload,
                                        "phase": val.get("phase"),
                                        "task_name": getattr(task, "name", None),
                                        "task_index": i,
                                        "interrupt_index": j,
                                    }
                                )
                            elif val is not None:
                                candidates.append(
                                    {
                                        "value": {"message": str(val)},
                                        "phase": None,
                                        "task_name": getattr(task, "name", None),
                                        "task_index": i,
                                        "interrupt_index": j,
                                    }
                                )
                return candidates

            def _select_candidate(candidates: list[dict[str, Any]], source: str) -> Optional[Dict[str, Any]]:
                if not candidates:
                    return None

                if interrupt_id:
                    exact_matches = [
                        candidate
                        for candidate in candidates
                        if candidate.get("value", {}).get("_interrupt_id") == interrupt_id
                    ]
                    if exact_matches:
                        chosen = exact_matches[-1]
                        logger.info(
                            "_extract_interrupt_from_state: selected %s interrupt by id=%s from task=%s",
                            source,
                            interrupt_id,
                            chosen.get("task_name"),
                        )
                        return chosen["value"]

                if resolved_phase:
                    phase_matches = [
                        candidate for candidate in candidates
                        if candidate.get("phase") == resolved_phase
                        or candidate.get("task_name") == resolved_phase
                    ]
                    if phase_matches:
                        chosen = phase_matches[-1]
                        logger.info(
                            "_extract_interrupt_from_state: selected %s interrupt for phase=%s from task=%s",
                            source,
                            resolved_phase,
                            chosen.get("task_name"),
                        )
                        return chosen["value"]

                chosen = candidates[-1]
                logger.info(
                    "_extract_interrupt_from_state: selected latest %s interrupt from task=%s phase=%s",
                    source,
                    chosen.get("task_name"),
                    chosen.get("phase"),
                )
                return chosen["value"]

            current_candidates = _extract_candidates(list(snapshot.tasks))
            selected = _select_candidate(current_candidates, "snapshot")
            if selected is not None:
                return selected

            # Also try subgraph states if available
            try:
                async for state_and_meta in engine.compiled_workflow.aget_state_history(config):
                    if state_and_meta and state_and_meta.tasks:
                        history_candidates = _extract_candidates(list(state_and_meta.tasks))
                        selected = _select_candidate(history_candidates, "history")
                        if selected is not None:
                            return selected
                    break  # Only check most recent history entry
            except Exception:
                pass  # History traversal is best-effort

            logger.debug("_extract_interrupt_from_state: no interrupts found in any tasks")
        except Exception:
            logger.warning("Failed to extract interrupt from state", exc_info=True)
        return None

    @staticmethod
    def _create_engine(client_id: str, workflow_id: str, session_id: str = "") -> tuple[PlanEngine, Any]:
        """Create a new PlanEngine instance with a progress callback.

        Returns a (engine, progress_callback) tuple so callers can inject
        the callback into config["configurable"].
        """
        from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine as _PlanEngine

        app_context: AppContext = get_app_context()
        checkpointer = CheckpointerFactory.create_checkpointer()
        set_plan_ws_manager(manager)

        progress_callback = PlanDispatcher._make_progress_callback(client_id, workflow_id)

        blob_storage = getattr(app_context, "blob_storage", None)
        if blob_storage is None:
            try:
                from graph_kb_api.storage.blob_storage import BlobStorage

                blob_storage = BlobStorage.from_env()
                setattr(app_context, "blob_storage", blob_storage)
            except Exception:
                logger.warning("PlanDispatcher failed to initialize blob storage", exc_info=True)
        artifact_service = None
        if blob_storage:
            from graph_kb_api.flows.v3.services.artifact_service import ArtifactService

            # Use actual session_id for artifact blob paths so artifacts are
            # retrievable by downstream nodes and the download endpoint.
            artifact_service = ArtifactService(blob_storage, session_id or str(uuid.uuid4()))

        # Build WorkflowContext with all dependencies (Req 20.1)
        workflow_context = WorkflowContext.from_app_context(
            app_context,
            blob_storage=blob_storage,
            checkpointer=checkpointer,
            artifact_service=artifact_service,
        )

        engine: PlanEngine = _PlanEngine(workflow_context=workflow_context)
        return (engine, progress_callback)

    @staticmethod
    def _make_progress_callback(
        client_id: str,
        workflow_id: str,
        *,
        session_id: str = "",
        thread_id: str = "",
        user_id: str = "",
    ) -> Any:
        """Create a fire-and-forget progress callback for the given client/session (Req 29.1, 29.2)."""
        async def progress_callback(event: Dict[str, Any]) -> None:
            try:
                await PlanDispatcher._emit_phase_progress(client_id, workflow_id, event)
                phase = event.get("phase")
                if session_id and thread_id and user_id and isinstance(phase, str):
                    await PlanDispatcher._persist_session_to_db(
                        session_id=session_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        workflow_status="running",
                        current_phase=phase,
                        completed_phases=PlanDispatcher._infer_completed_phases(phase),
                    )
            except Exception:
                pass  # Silently drop — workflow must continue (Req 29.1)
        return progress_callback

    # ── Session management ─────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[PlanSession]:
        """Look up a plan session by ID."""
        return self._sessions.get(session_id)

    @staticmethod
    def _validate_session_owner(session: PlanSession, client_id: str, session_id: str) -> bool:
        """Verify that *client_id* owns *session* (Req 20.6)."""
        registered_client = session.get("client_id")
        if registered_client is None:
            return True
        return registered_client == client_id

    async def _ensure_session_owner(
        self,
        client_id: str,
        workflow_id: str,
        session_id: str,
        session: PlanSession | None = None,
    ) -> bool:
        """Validate session ownership before rebinding a client to a session."""

        if session is not None:
            if self._validate_session_owner(session, client_id, session_id):
                return True
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Plan session is owned by a different client: {session_id}",
                "SESSION_OWNER_MISMATCH",
            )
            return False

        try:
            async with get_session() as db:
                repo = PlanSessionRepository(db)
                persisted = await repo.get(session_id)
        except Exception:
            logger.warning("Failed to validate plan session ownership", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to validate session ownership: {session_id}",
                "ENGINE_ERROR",
            )
            return False

        if not persisted:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {session_id}",
                "SESSION_NOT_FOUND",
            )
            return False

        if persisted.user_id != client_id:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Plan session is owned by a different client: {session_id}",
                "SESSION_OWNER_MISMATCH",
            )
            return False

        return True

    def _register_session(
        self,
        session_id: str,
        engine: PlanEngine,
        config: RunnableConfig,
        thread_id: str,
        user_id: str,
        client_id: str,
        workflow_id: str,
    ) -> None:
        """Register a plan session.

        Note: Config is stored by reference (not deep-copied) because LangGraph
        configs contain non-serializable objects (ChatOpenAI with httpx clients).
        Configs are used read-only for graph execution, so reference storage is safe.
        """
        self._sessions[session_id] = PlanSession(
            engine=engine,
            config=config,  # Reference only - contains non-picklable LLM clients
            session_id=session_id,
            thread_id=thread_id,
            user_id=user_id,
            client_id=client_id,
            workflow_id=workflow_id,
            running_task=None,
        )
        manager.register_session(session_id, client_id)

    async def _cancel_running_task(self, session: PlanSession) -> bool:
        """Cancel the running agent task for a session, if any."""
        task: Optional[asyncio.Task] = session.get("running_task")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            session["running_task"] = None
            return True
        session["running_task"] = None
        return False

    # ── Event handlers ─────────────────────────────────────────

    async def handle_start(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.start (Req 20.1, 20.3)."""
        try:
            validated = PlanStartPayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.start payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        _debug_log(
            "PLAN_START",
            client_id=client_id,
            name=validated.name,
            description=validated.description,
        )

        # In mock playback mode, each brand-new plan workflow should start
        # from the beginning of the recording set. Rewinds must happen here,
        # not implicitly during arbitrary LLMService construction.
        try:
            from graph_kb_api.config.settings import settings
            from graph_kb_api.core.llm_recorder import LLMRecorder

            if settings.llm_recording_mode == "mock":
                LLMRecorder.from_settings().rewind_mock_run()
        except Exception:
            logger.warning("Failed to rewind mock LLM recorder for new plan session", exc_info=True)

        session_id = str(uuid.uuid4())
        thread_id = f"plan-{session_id}"
        cfg: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        engine, _progress_callback = self._create_engine(client_id, workflow_id, session_id=session_id)
        cfg: RunnableConfig = engine.get_config_with_services(cfg)
        cfg["configurable"]["progress_callback"] = self._make_progress_callback(
            client_id,
            workflow_id,
            session_id=session_id,
            thread_id=thread_id,
            user_id=client_id,
        )
        cfg["configurable"]["client_id"] = client_id
        self._register_session(session_id, engine, cfg, thread_id, client_id, client_id, workflow_id)

        # Persist session to DB for browser-close resume
        await self._persist_session_to_db(
            session_id=session_id,
            thread_id=thread_id,
            user_id=client_id,
            workflow_status="running",
            current_phase="context",
            name=validated.name,
            description=validated.description,
        )

        initial_state: Dict[str, Any] = {
            "context": {"spec_name": validated.name},
            "session_id": session_id,
        }
        if validated.description:
            initial_state["context"]["spec_description"] = validated.description

        # Budget defaults: payload overrides > settings > engine defaults (200/500k/1800)
        _budget_overrides = False
        if validated.max_llm_calls is not None:
            initial_state["max_llm_calls"] = validated.max_llm_calls
            _budget_overrides = True
        if validated.max_tokens is not None:
            initial_state["max_tokens"] = validated.max_tokens
            _budget_overrides = True
        if validated.max_wall_clock_s is not None:
            initial_state["max_wall_clock_s"] = validated.max_wall_clock_s
            _budget_overrides = True

        if not _budget_overrides:
            try:
                ctx: AppContext = get_app_context()
                if ctx and ctx.graph_kb_facade and ctx.graph_kb_facade.metadata_store is not None:
                    from graph_kb_api.routers.settings import _load_extra_settings

                    extra = _load_extra_settings(ctx.graph_kb_facade.metadata_store)
                    if extra.get("plan_max_llm_calls") is not None:
                        initial_state["max_llm_calls"] = extra["plan_max_llm_calls"]
                    if extra.get("plan_max_tokens") is not None:
                        initial_state["max_tokens"] = extra["plan_max_tokens"]
                    if extra.get("plan_max_wall_clock_s") is not None:
                        initial_state["max_wall_clock_s"] = extra["plan_max_wall_clock_s"]
            except Exception:
                logger.debug("Could not load plan budget defaults from settings")

        session = self.get_session(session_id)
        try:
            result = await engine.start_workflow(
                user_query=validated.name,
                user_id=client_id,
                session_id=session_id,
                config=cfg,
                initial_state=initial_state,
            )
            if session:
                session["running_task"] = None
            await self._persist_runtime_snapshot(
                session_id,
                thread_id,
                client_id,
                engine,
                cfg,
                fallback_phase="context",
                result=result,
            )
            latest_state = await engine.get_workflow_state(cfg)
            if await self._recover_stale_terminal_completion(
                session_id=session_id,
                thread_id=thread_id,
                user_id=client_id,
                client_id=client_id,
                workflow_id=workflow_id,
                engine=engine,
                config=cfg,
                state=latest_state,
                result=result,
            ):
                return
            if await self._check_and_emit_error(result, client_id, workflow_id, session_id):
                return
            latest_state = await engine.get_workflow_state(cfg)
            if await self._emit_terminal_status_if_needed(
                state=latest_state,
                result=result,
                client_id=client_id,
                workflow_id=workflow_id,
                session_id=session_id,
                fallback_phase="context",
            ):
                return
            idata = await self._extract_interrupt_from_state(engine, cfg)
            if idata:
                idata.setdefault("session_id", session_id)
                # Attach budget info so BudgetIndicator can display limits
                state = await engine.get_workflow_state(cfg)
                if state:
                    budget = state.get("budget", {})
                    idata["budget"] = {
                        "remainingLlmCalls": budget.get("remaining_llm_calls", 0),
                        "tokensUsed": budget.get("tokens_used", 0),
                        "maxLlmCalls": budget.get("max_llm_calls", 200),
                        "maxTokens": budget.get("max_tokens", 500_000),
                    }
                await self._emit_phase_prompt(client_id, workflow_id, idata)
                return
            logger.info(
                "Plan workflow completed without interrupt",
                extra={"session_id": session_id},
            )
            # No document generated - notify frontend
            try:
                await emit_error(
                    session_id=session_id,
                    message="Plan workflow completed without user interaction.",
                    code="NO_INTERRUPT",
                    client_id=client_id,
                )
            except Exception:
                pass
        except Exception as e:
            if session:
                session["running_task"] = None
            logger.error(f"Plan start failed: {e}", exc_info=True)
            await self._persist_session_to_db(
                session_id=session_id,
                thread_id=thread_id,
                user_id=client_id,
                workflow_status="error",
                current_phase="context",
            )
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to start plan workflow: {e}",
                "ENGINE_ERROR",
            )

    async def handle_phase_input(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.phase.input — resume workflow (Req 20.4)."""
        try:
            validated = PlanPhaseInputPayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.phase.input payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not session:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {validated.session_id}",
                "SESSION_NOT_FOUND",
            )
            return

        if not await self._ensure_session_owner(client_id, workflow_id, validated.session_id, session):
            return

        running_task = session.get("running_task")
        if (
            running_task is not None
            and not running_task.done()
            and running_task is not asyncio.current_task()
        ):
            logger.info(
                "Ignoring overlapping plan.phase.input while another resume is active",
                extra={
                    "session_id": validated.session_id,
                    "phase": validated.phase.value,
                },
            )
            return

        session["client_id"] = client_id
        session["workflow_id"] = workflow_id
        manager.register_session(validated.session_id, client_id)
        engine: PlanEngine = session["engine"]
        config: RunnableConfig = session["config"]
        config["configurable"]["client_id"] = client_id
        config["configurable"]["progress_callback"] = self._make_progress_callback(
            client_id,
            workflow_id,
            session_id=validated.session_id,
            thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
            user_id=session.get("user_id", client_id),
        )

        # Ensure progress_callback and client_id are in config (Req 1.1, 1.3).
        # client_id may change on reconnect; progress_callback must match.
        config["configurable"]["client_id"] = client_id
        config["configurable"]["progress_callback"] = self._make_progress_callback(
            client_id,
            workflow_id,
            session_id=validated.session_id,
            thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
            user_id=session.get("user_id", client_id),
        )

        _debug_log(
            "PLAN_PHASE_INPUT",
            client_id=client_id,
            session_id=validated.session_id,
            phase=validated.phase.value,
        )

        submitted_interrupt_id = (validated.data or {}).get("interrupt_id")
        current_interrupt = await self._extract_interrupt_from_state(
            engine,
            config,
            preferred_phase=validated.phase.value,
            interrupt_id=submitted_interrupt_id if isinstance(submitted_interrupt_id, str) else None,
        )
        current_state = await engine.get_workflow_state(config)
        current_status = (current_state or {}).get("workflow_status", "running")

        if not current_interrupt:
            if self._is_terminal_status(current_status):
                logger.info(
                    "Ignoring plan.phase.input for terminal session with no pending interrupt",
                    extra={
                        "session_id": validated.session_id,
                        "workflow_status": current_status,
                    },
                )
                await self._persist_runtime_snapshot(
                    validated.session_id,
                    session.get("thread_id", f"plan-{validated.session_id}"),
                    session.get("user_id", client_id),
                    engine,
                    config,
                    fallback_phase=validated.phase.value,
                    workflow_status=current_status,
                )
                return

        decision = (validated.data or {}).get("decision")
        allowed_option_ids = self._get_interrupt_option_ids(current_interrupt)
        if isinstance(decision, str) and allowed_option_ids and decision not in allowed_option_ids:
            logger.warning(
                "Ignoring mismatched phase input decision '%s'; allowed=%s",
                decision,
                sorted(allowed_option_ids),
                extra={
                    "session_id": validated.session_id,
                    "phase": validated.phase.value,
                },
            )
            current_interrupt.setdefault("session_id", validated.session_id)
            await self._emit_phase_prompt(client_id, workflow_id, current_interrupt)
            return

        # Handle budget increase from HITL interrupt response.
        # When budget exhaustion triggers an interrupt() in SubgraphAwareNode,
        # the user can choose "increase_budget". The budget update must be
        # applied to state BEFORE resuming so the re-executed node sees it.
        input_data = validated.data or {}
        budget_update: Dict[str, Any] = {}
        if input_data.get("decision") == "increase_budget" and not self._is_budget_interrupt(current_interrupt):
            logger.warning(
                "Ignoring mismatched budget increase request for non-budget interrupt",
                extra={
                    "session_id": validated.session_id,
                    "phase": validated.phase.value,
                    "interrupt_id": submitted_interrupt_id,
                },
            )
            if current_interrupt:
                current_interrupt.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, current_interrupt)
            return

        if input_data.get("decision") == "increase_budget":
            try:
                state = await engine.get_workflow_state(config)
                if state:
                    budget = state.get("budget", {})
                    if input_data.get("max_llm_calls") is not None:
                        old_max = budget.get("max_llm_calls", 200)
                        additional = input_data["max_llm_calls"] - old_max
                        budget_update["max_llm_calls"] = input_data["max_llm_calls"]
                        remaining = budget.get("remaining_llm_calls", 0)
                        budget_update["remaining_llm_calls"] = max(remaining + additional, 0)
                    else:
                        # No explicit value provided — apply 50% default increase
                        old_max = budget.get("max_llm_calls", 200)
                        additional = max(int(old_max * 0.5), 10)
                        budget_update["max_llm_calls"] = old_max + additional
                        remaining = budget.get("remaining_llm_calls", 0)
                        budget_update["remaining_llm_calls"] = remaining + additional
                    if input_data.get("max_tokens") is not None:
                        budget_update["max_tokens"] = input_data["max_tokens"]
                    if input_data.get("max_wall_clock_s") is not None:
                        budget_update["max_wall_clock_s"] = input_data["max_wall_clock_s"]
                    # Reset the wall-clock timer so the full budget window
                    # is available from this point forward.  Without this,
                    # a wall-clock exhaustion would immediately re-trigger
                    # on the next BudgetGuard.check() after resume.
                    budget_update["started_at"] = datetime.now(UTC).isoformat()
                    await engine.workflow.aupdate_state(
                        config,
                        {
                            "workflow_status": "running",
                            "budget": {**budget, **budget_update},
                        },
                    )
                    logger.info(
                        "Plan phase input: updated budget for HITL resume",
                        extra={
                            "session_id": validated.session_id,
                            "budget_update": budget_update,
                        },
                    )
            except Exception as e:
                logger.warning("Failed to update budget for HITL resume: %s", e, exc_info=True)

        # Inject the computed budget_update into resume data so the subgraph node
        # can propagate it into the subgraph's internal state (aupdate_state only
        # updates the parent graph, but the subgraph is resumed mid-execution).
        resume_data = dict(validated.data or {})
        if input_data.get("decision") == "increase_budget" and budget_update:
            resume_data["budget_update"] = budget_update
        interrupt_id = current_interrupt.get("_interrupt_id") if current_interrupt else None

        try:
            coro = engine.resume_workflow(
                workflow_id=validated.session_id,
                user_id=client_id,
                input_data=resume_data,
                config=config,
                interrupt_id=interrupt_id if isinstance(interrupt_id, str) else None,
            )
            session["running_task"] = asyncio.current_task()

            try:
                result = await coro
                session["running_task"] = None
                await self._persist_runtime_snapshot(
                    validated.session_id,
                    session.get("thread_id", f"plan-{validated.session_id}"),
                    session.get("user_id", client_id),
                    engine,
                    config,
                    fallback_phase=validated.phase.value,
                    result=result,
                )
                latest_state = await engine.get_workflow_state(config)
                if await self._recover_stale_terminal_completion(
                    session_id=validated.session_id,
                    thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                    user_id=session.get("user_id", client_id),
                    client_id=client_id,
                    workflow_id=workflow_id,
                    engine=engine,
                    config=config,
                    state=latest_state,
                    result=result,
                ):
                    return
                if await self._check_and_emit_error(
                    result,
                    client_id,
                    workflow_id,
                    validated.session_id,
                ):
                    return
                latest_state = await engine.get_workflow_state(config)
                if await self._emit_terminal_status_if_needed(
                    state=latest_state,
                    result=result,
                    client_id=client_id,
                    workflow_id=workflow_id,
                    session_id=validated.session_id,
                    fallback_phase=validated.phase.value,
                ):
                    return
                latest_status = self._merge_runtime_state(latest_state, result).get("workflow_status")
                if self._is_terminal_status(latest_status):
                    logger.info(
                        "Plan workflow reached terminal status after phase input",
                        extra={
                            "session_id": validated.session_id,
                            "workflow_status": latest_status,
                        },
                    )
                    return
                idata: dict[str, Any] | None = await self._extract_interrupt_from_state(engine, config)
                if idata:
                    idata.setdefault("session_id", validated.session_id)
                    await self._emit_phase_prompt(client_id, workflow_id, idata)
                    return
                # plan.complete / plan.error already emitted by FinalizeNode (or error nodes)
                # No additional emission needed here
                logger.info(
                    "Plan workflow completed for session %s",
                    validated.session_id,
                )
            except asyncio.CancelledError:
                session["running_task"] = None
                logger.info(
                    "Plan phase input cancelled",
                    extra={
                        "session_id": validated.session_id,
                        "phase": validated.phase.value,
                    },
                )
                return
        except Exception as e:
            session["running_task"] = None
            logger.error(f"Plan phase input failed: {e}", exc_info=True)
            await self._persist_session_to_db(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                workflow_status="error",
                current_phase=validated.phase.value,
                completed_phases=self._infer_completed_phases(validated.phase.value),
            )
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to process plan phase input: {e}",
                "ENGINE_ERROR",
                validated.phase,
            )

    async def handle_navigate(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.navigate — CASCADE_MAP navigation (Req 20.5)."""
        try:
            validated = PlanNavigatePayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.navigate payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not session:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {validated.session_id}",
                "SESSION_NOT_FOUND",
            )
            return

        engine: PlanEngine = session["engine"]
        config: RunnableConfig = session["config"]

        _debug_log(
            "PLAN_NAVIGATE",
            client_id=client_id,
            session_id=validated.session_id,
            target_phase=validated.target_phase.value,
            confirm_cascade=validated.confirm_cascade,
        )

        # Without confirmation: analyze and emit cascade confirmation
        if not validated.confirm_cascade:
            target = validated.target_phase.value
            # Use analyze_navigate (read-only) — does NOT mutate state
            nav_result = await engine.analyze_navigate(target, config)
            content_changed = nav_result.get("content_changed", False)
            dirty = nav_result.get("dirty_phases", [])
            estimated = nav_result.get("estimated_llm_calls", 0)
            downstream = CASCADE_MAP.get(target, [])

            if content_changed and dirty:
                # Content changed — confirm re-run with cost estimate
                await manager.send_event(
                    client_id=client_id,
                    event_type="plan.cascade.confirm",
                    workflow_id=workflow_id,
                    data={
                        "session_id": validated.session_id,
                        "targetPhase": target,
                        "affectedPhases": downstream,
                        "dirtyPhases": dirty,
                        "estimatedLlmCalls": estimated,
                    },
                )
            else:
                # No change — navigate to target phase without cascade
                await engine.navigate_to_phase(target, config)
                await engine._cancel_stale_interrupts(config)
                result = await engine.compiled_workflow.ainvoke(None, config=config)
                session["running_task"] = None
                idata = await self._extract_interrupt_from_state(engine, config)
                if idata:
                    idata.setdefault("session_id", validated.session_id)
                    await self._emit_phase_prompt(client_id, workflow_id, idata)
            return

        # With confirmation: cancel + navigate
        was_cancelled = await self._cancel_running_task(session)
        if was_cancelled:
            logger.info(
                "Cancelled running plan task for navigation",
                extra={
                    "session_id": validated.session_id,
                    "target_phase": validated.target_phase.value,
                },
            )

        try:
            state = await engine.get_workflow_state(config)
            if state is None:
                await self._emit_plan_error(
                    client_id,
                    workflow_id,
                    "No workflow state found for navigation",
                    "STATE_NOT_FOUND",
                )
                return

            target_phase = validated.target_phase.value

            logger.info(
                "Plan navigate: restarting from %s via Command(goto=...)",
                target_phase,
                extra={"session_id": validated.session_id},
            )

            # Use restart_from_phase which updates state with Command(goto=...)
            # then invokes the graph from the target phase — not from the
            # previous interrupt point (which was the old broken behavior).
            result = await engine.restart_from_phase(target_phase, config)
            session["running_task"] = None
            idata = await self._extract_interrupt_from_state(engine, config)
            if idata:
                idata.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, idata)
            elif await self._check_and_emit_error(
                result,
                client_id,
                workflow_id,
                validated.session_id,
            ):
                return
        except Exception as e:
            logger.error(f"Plan navigate failed: {e}", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to navigate: {e}",
                "ENGINE_ERROR",
                validated.target_phase,
            )

    async def handle_resume(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.resume — load checkpoint, update budget if needed, re-emit prompt.

        Supports budget exhaustion recovery: when the workflow is paused due to
        budget exhaustion, the user can provide increased budget limits via
        max_llm_calls, max_tokens, or max_wall_clock_s fields. The handler
        updates the budget state and resets workflow_status before resuming
        (Requirements 20.2, 28.3).
        """
        try:
            validated = PlanResumePayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.resume payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not await self._ensure_session_owner(client_id, workflow_id, validated.session_id, session):
            return

        if not session:
            thread_id = f"plan-{validated.session_id}"
            cfg: RunnableConfig = {
                "configurable": {
                    "thread_id": thread_id,
                }
            }
            engine, _progress_callback = self._create_engine(client_id, workflow_id, session_id=validated.session_id)
            cfg = engine.get_config_with_services(cfg)
            cfg["configurable"]["progress_callback"] = self._make_progress_callback(
                client_id,
                workflow_id,
                session_id=validated.session_id,
                thread_id=thread_id,
                user_id=client_id,
            )
            cfg["configurable"]["client_id"] = client_id
            self._register_session(
                validated.session_id,
                engine,
                cfg,
                thread_id,
                client_id,
                client_id,
                workflow_id,
            )
            session = self.get_session(validated.session_id)
            assert session is not None  # just registered above
        else:
            session["client_id"] = client_id
            session["workflow_id"] = workflow_id
            manager.register_session(validated.session_id, client_id)

        engine = session["engine"]
        config: RunnableConfig = session["config"]

        # Ensure progress_callback and client_id are in config (Req 1.1, 1.3).
        config["configurable"]["client_id"] = client_id
        config["configurable"]["progress_callback"] = self._make_progress_callback(
            client_id,
            workflow_id,
            session_id=validated.session_id,
            thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
            user_id=session.get("user_id", client_id),
        )

        _debug_log(
            "PLAN_RESUME",
            client_id=client_id,
            session_id=validated.session_id,
        )

        try:
            state = await engine.get_workflow_state(config)
            if state is None:
                await self._emit_plan_error(
                    client_id,
                    workflow_id,
                    f"No checkpoint for plan session: {validated.session_id}",
                    "SESSION_NOT_FOUND",
                )
                return

            # If workflow was paused due to budget exhaustion, update budget
            # limits and reset status so the workflow can resume (Req 28.3)
            if state.get("workflow_status") == "budget_exhausted":
                budget = state.get("budget", {})
                budget_update: Dict[str, Any] = {}

                if validated.max_llm_calls is not None:
                    # Increase remaining by the delta between new and old max
                    old_max = budget.get("max_llm_calls", 200)
                    additional = validated.max_llm_calls - old_max
                    budget_update["max_llm_calls"] = validated.max_llm_calls
                    remaining = budget.get("remaining_llm_calls")
                    budget_update["remaining_llm_calls"] = max(
                        (remaining if remaining is not None else 0) + additional, 0
                    )
                if validated.max_tokens is not None:
                    budget_update["max_tokens"] = validated.max_tokens
                if validated.max_wall_clock_s is not None:
                    budget_update["max_wall_clock_s"] = validated.max_wall_clock_s

                # Reset the wall-clock timer so the full budget window
                # is available from this point forward.
                budget_update["started_at"] = datetime.now(UTC).isoformat()

                state_update: Dict[str, Any] = {
                    "workflow_status": "running",
                }
                if budget_update:
                    state_update["budget"] = {**budget, **budget_update}

                await engine.workflow.aupdate_state(config, state_update)

                logger.info(
                    "Plan resume: updated budget and reset status from budget_exhausted",
                    extra={
                        "session_id": validated.session_id,
                        "budget_update": budget_update,
                    },
                )

                # Emit plan.state so frontend can reconstruct UI before
                # the workflow resumes and starts emitting phase events.
                completed = self._normalize_completed_phases(state)
                current_phase = self._resolve_current_phase(state)
                updated_budget = {**budget, **budget_update} if budget_update else budget
                try:
                    await manager.send_event(
                        client_id=client_id,
                        event_type="plan.state",
                        workflow_id=workflow_id,
                        data=self._build_plan_state_payload(
                            session_id=validated.session_id,
                            state=state,
                            workflow_status="running",
                            completed_phases=completed,
                            current_phase=current_phase,
                            budget=updated_budget,
                        ),
                    )
                except Exception as e:
                    logger.warning(f"plan.resume budget path emit plan.state failed: {e}")

                # Check for pending interrupts before deciding how to resume.
                # If the graph already ended (user previously chose
                # "Accept Current Results"), there are no interrupts to
                # resume from and Command(resume={}) would fail silently.
                snapshot = await engine.compiled_workflow.aget_state(config)
                has_pending_interrupts = bool(
                    snapshot
                    and snapshot.tasks
                    and any(getattr(t, "interrupts", None) for t in snapshot.tasks)
                )

                try:
                    if has_pending_interrupts:
                        result = await engine.resume_workflow(
                            workflow_id=validated.session_id,
                            user_id=client_id,
                            input_data=None,
                            config=config,
                        )
                    else:
                        # Graph has ended — budget is updated but there is
                        # no active interrupt to resume.  Signal the user
                        # that they need to navigate to the paused phase.
                        paused_phase = state.get("paused_phase", "")
                        logger.info(
                            "Plan resume: budget updated but graph already "
                            "ended (paused_phase=%s). "
                            "User should use plan.navigate to re-run.",
                            paused_phase,
                            extra={"session_id": validated.session_id},
                        )
                        await manager.send_event(
                            client_id=client_id,
                            event_type="plan.paused",
                            workflow_id=workflow_id,
                            data={
                                "session_id": validated.session_id,
                                "phase": paused_phase,
                                "status": "budget_recovered",
                                "message": (
                                    "Budget updated successfully. Use the "
                                    "phase navigator to re-run from where "
                                    "the workflow stopped."
                                ),
                            },
                        )
                        return

                    session["running_task"] = None
                    await self._persist_runtime_snapshot(
                        validated.session_id,
                        session.get("thread_id", f"plan-{validated.session_id}"),
                        session.get("user_id", client_id),
                        engine,
                        config,
                        result=result,
                    )
                    latest_state = await engine.get_workflow_state(config)
                    if await self._recover_stale_terminal_completion(
                        session_id=validated.session_id,
                        thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                        user_id=session.get("user_id", client_id),
                        client_id=client_id,
                        workflow_id=workflow_id,
                        engine=engine,
                        config=config,
                        state=latest_state,
                        result=result,
                    ):
                        return
                    if await self._check_and_emit_error(result, client_id, workflow_id, validated.session_id):
                        return
                    latest_state = await engine.get_workflow_state(config)
                    if await self._emit_terminal_status_if_needed(
                        state=latest_state,
                        result=result,
                        client_id=client_id,
                        workflow_id=workflow_id,
                        session_id=validated.session_id,
                    ):
                        return
                    latest_status = self._merge_runtime_state(latest_state, result).get("workflow_status")
                    if self._is_terminal_status(latest_status):
                        logger.info(
                            "Plan resume reached terminal status after budget increase",
                            extra={"session_id": validated.session_id, "workflow_status": latest_status},
                        )
                        return
                    idata = await self._extract_interrupt_from_state(engine, config)
                    if idata:
                        idata.setdefault("session_id", validated.session_id)
                        await self._emit_phase_prompt(client_id, workflow_id, idata)
                        return
                    logger.info(
                        "Plan resumed and completed after budget increase",
                        extra={"session_id": validated.session_id},
                    )
                except Exception as e:
                    session["running_task"] = None
                    logger.error(f"Plan resume workflow failed: {e}", exc_info=True)
                    await self._persist_session_to_db(
                        session_id=validated.session_id,
                        thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                        user_id=session.get("user_id", client_id),
                        workflow_status="error",
                    )
                    await self._emit_plan_error(
                        client_id,
                        workflow_id,
                        f"Failed to resume plan workflow: {e}",
                        "ENGINE_ERROR",
                    )
                return

            # Standard resume: provide current workflow state on reconnect (Req 29.3)
            completed = self._normalize_completed_phases(state)
            budget = state.get("budget", {})
            current_phase = self._resolve_current_phase(state)

            workflow_status = state.get("workflow_status", "running")
            if await self._recover_stale_terminal_completion(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                client_id=client_id,
                workflow_id=workflow_id,
                engine=engine,
                config=config,
                state=state,
            ):
                return
            if await self._emit_terminal_status_if_needed(
                state=state,
                result=None,
                client_id=client_id,
                workflow_id=workflow_id,
                session_id=validated.session_id,
            ):
                return
            await self._persist_runtime_snapshot(
                validated.session_id,
                session.get("thread_id", f"plan-{validated.session_id}"),
                session.get("user_id", client_id),
                engine,
                config,
                workflow_status=workflow_status,
            )

            # Emit current workflow state so the client can reconstruct
            # the UI on reconnect (Req 29.3). Sent as a dedicated event
            # because SpecPhasePromptData doesn't carry state fields.
            try:
                await manager.send_event(
                    client_id=client_id,
                    event_type="plan.state",
                    workflow_id=workflow_id,
                    data=self._build_plan_state_payload(
                        session_id=validated.session_id,
                        state=state,
                        workflow_status=workflow_status,
                        completed_phases=completed,
                        current_phase=current_phase,
                        budget=budget,
                    ),
                )
            except Exception as e:
                logger.warning(f"plan.resume emit plan.state failed: {e}")

            # Try to retrieve the actual interrupt payload for the correct prompt
            idata = await self._extract_interrupt_from_state(engine, config)
            if idata:
                idata.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, idata)
            elif self._is_terminal_status(workflow_status):
                logger.info(
                    "Plan resume reached terminal workflow state with no pending interrupt",
                    extra={
                        "session_id": validated.session_id,
                        "workflow_status": workflow_status,
                    },
                )
                return
            else:
                running_task = session.get("running_task")
                if running_task is not None and not running_task.done():
                    logger.info(
                        "Plan resume found an active running task; skipping synthetic prompt",
                        extra={
                            "session_id": validated.session_id,
                            "workflow_status": workflow_status,
                        },
                    )
                    return

                phase_order = list(self._PHASE_ORDER)
                state_phase = state.get("current_phase")
                if isinstance(state_phase, str) and state_phase in phase_order:
                    logger.info(
                        "Plan resume restored active phase without pending interrupt",
                        extra={
                            "session_id": validated.session_id,
                            "current_phase": state_phase,
                            "workflow_status": workflow_status,
                        },
                    )
                    return

                recovery_phase = self._resolve_current_phase(state)
                logger.warning(
                    "Plan resume found stale non-terminal state with no interrupt; "
                    "restarting first incomplete phase '%s'",
                    recovery_phase,
                    extra={
                        "session_id": validated.session_id,
                        "workflow_status": workflow_status,
                    },
                )
                try:
                    result = await engine.restart_from_phase(recovery_phase, config)
                    await self._persist_runtime_snapshot(
                        validated.session_id,
                        session.get("thread_id", f"plan-{validated.session_id}"),
                        session.get("user_id", client_id),
                        engine,
                        config,
                        fallback_phase=recovery_phase,
                        result=result,
                    )
                    if await self._check_and_emit_error(
                        result,
                        client_id,
                        workflow_id,
                        validated.session_id,
                    ):
                        return

                    recovered_interrupt = await self._extract_interrupt_from_state(engine, config)
                    if recovered_interrupt:
                        recovered_interrupt.setdefault("session_id", validated.session_id)
                        await self._emit_phase_prompt(client_id, workflow_id, recovered_interrupt)
                        return

                    refreshed_state = await engine.get_workflow_state(config)
                    refreshed_status = (
                        (refreshed_state or {}).get("workflow_status")
                        or (result or {}).get("workflow_status")
                        or workflow_status
                    )
                    if self._is_terminal_status(refreshed_status):
                        logger.info(
                            "Plan resume recovery reached terminal workflow state",
                            extra={
                                "session_id": validated.session_id,
                                "workflow_status": refreshed_status,
                            },
                        )
                        return

                    logger.info(
                        "Plan resume recovery restarted phase without a new interrupt; "
                        "awaiting subsequent progress events",
                        extra={
                            "session_id": validated.session_id,
                            "phase": recovery_phase,
                            "workflow_status": refreshed_status,
                        },
                    )
                    return
                except Exception as e:
                    logger.error(f"Plan resume recovery failed: {e}", exc_info=True)
                    await self._emit_plan_error(
                        client_id,
                        workflow_id,
                        f"Failed to recover plan session: {e}",
                        "ENGINE_ERROR",
                    )
                    return
        except Exception as e:
            logger.error(f"Plan resume failed: {e}", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to resume plan session: {e}",
                "ENGINE_ERROR",
            )

    async def handle_pause(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.pause — acknowledge pause (Req 20.2)."""
        try:
            validated = PlanPausePayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.pause payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        _debug_log(
            "PLAN_PAUSE",
            client_id=client_id,
            session_id=validated.session_id,
        )

        await manager.send_event(
            client_id=client_id,
            event_type="plan.paused",
            workflow_id=workflow_id,
            data={
                "status": "paused",
                "message": "Plan session paused.",
                "session_id": validated.session_id,
            },
        )
        session = self.get_session(validated.session_id)
        if session:
            await self._persist_session_to_db(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                workflow_status="paused",
            )

    async def handle_retry(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.retry — retry failed phase (Req 20.2)."""
        try:
            validated = PlanRetryPayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.retry payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not session:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {validated.session_id}",
                "SESSION_NOT_FOUND",
            )
            return

        session["client_id"] = client_id
        session["workflow_id"] = workflow_id
        manager.register_session(validated.session_id, client_id)
        engine: PlanEngine = session["engine"]
        config: RunnableConfig = session["config"]

        _debug_log(
            "PLAN_RETRY",
            client_id=client_id,
            session_id=validated.session_id,
        )

        try:
            # If workflow was paused (e.g. due to storage failure), reset status
            # so the workflow can resume from the paused phase (Req 27.2).
            try:
                state = await engine.get_workflow_state(config)
                if state and state.get("workflow_status") in ("paused", "error"):
                    await engine.workflow.aupdate_state(config, {"workflow_status": "running"})
                    logger.info(
                        "Plan retry: reset workflow_status from %s to running",
                        state.get("workflow_status"),
                        extra={"session_id": validated.session_id},
                    )
            except Exception:
                pass  # Best-effort; resume will still be attempted

            result = await engine.resume_workflow(
                workflow_id=validated.session_id,
                user_id=client_id,
                input_data=None,
                config=config,
            )
            session["running_task"] = None
            await self._persist_runtime_snapshot(
                validated.session_id,
                session.get("thread_id", f"plan-{validated.session_id}"),
                session.get("user_id", client_id),
                engine,
                config,
                fallback_phase=(validated.phase.value if validated.phase else None),
                result=result,
            )
            latest_state = await engine.get_workflow_state(config)
            if await self._recover_stale_terminal_completion(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                client_id=client_id,
                workflow_id=workflow_id,
                engine=engine,
                config=config,
                state=latest_state,
                result=result,
            ):
                return
            if await self._check_and_emit_error(
                result,
                client_id,
                workflow_id,
                validated.session_id,
            ):
                return
            latest_state = await engine.get_workflow_state(config)
            if await self._emit_terminal_status_if_needed(
                state=latest_state,
                result=result,
                client_id=client_id,
                workflow_id=workflow_id,
                session_id=validated.session_id,
                fallback_phase=(validated.phase.value if validated.phase else None),
            ):
                return
            idata = await self._extract_interrupt_from_state(engine, config)
            if idata:
                idata.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, idata)
                return
            logger.info(
                "Plan retry completed",
                extra={"session_id": validated.session_id},
            )
        except Exception as e:
            session["running_task"] = None
            logger.error(f"Plan retry failed: {e}", exc_info=True)
            await self._persist_session_to_db(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                workflow_status="error",
            )
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to retry plan phase: {e}",
                "ENGINE_ERROR",
            )

    async def handle_reconnect(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.reconnect — update client_id on WebSocket reconnect.

        Re-emits the current plan.state so the frontend can reconstruct
        the UI without resuming execution (Req 29.3).
        """
        try:
            validated = PlanReconnectPayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.reconnect payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not session:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {validated.session_id}",
                "SESSION_NOT_FOUND",
            )
            return

        if not await self._ensure_session_owner(client_id, workflow_id, validated.session_id, session):
            return

        # Update client_id and workflow_id for the reconnected client
        session["client_id"] = client_id
        session["workflow_id"] = workflow_id
        manager.register_session(validated.session_id, client_id)
        engine = session["engine"]
        config: RunnableConfig = session["config"]

        # Ensure progress_callback points to the new client
        config["configurable"]["client_id"] = client_id
        config["configurable"]["progress_callback"] = self._make_progress_callback(
            client_id,
            workflow_id,
            session_id=validated.session_id,
            thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
            user_id=session.get("user_id", client_id),
        )

        _debug_log(
            "PLAN_RECONNECT",
            client_id=client_id,
            session_id=validated.session_id,
        )

        # Re-emit current state so the frontend can reconstruct the UI
        try:
            state = await engine.get_workflow_state(config)
            if state is None:
                await self._emit_plan_error(
                    client_id,
                    workflow_id,
                    f"No checkpoint for plan session: {validated.session_id}",
                    "SESSION_NOT_FOUND",
                )
                return

            completed = self._normalize_completed_phases(state)
            budget = state.get("budget", {})
            current_phase = self._resolve_current_phase(state)

            workflow_status = state.get("workflow_status", "running")
            if await self._recover_stale_terminal_completion(
                session_id=validated.session_id,
                thread_id=session.get("thread_id", f"plan-{validated.session_id}"),
                user_id=session.get("user_id", client_id),
                client_id=client_id,
                workflow_id=workflow_id,
                engine=engine,
                config=config,
                state=state,
            ):
                return
            if await self._emit_terminal_status_if_needed(
                state=state,
                result=None,
                client_id=client_id,
                workflow_id=workflow_id,
                session_id=validated.session_id,
            ):
                return
            await self._persist_runtime_snapshot(
                validated.session_id,
                session.get("thread_id", f"plan-{validated.session_id}"),
                session.get("user_id", client_id),
                engine,
                config,
                workflow_status=workflow_status,
            )

            state_data: Dict[str, Any] = self._build_plan_state_payload(
                session_id=validated.session_id,
                state=state,
                workflow_status=workflow_status,
                completed_phases=completed,
                current_phase=current_phase,
                budget=budget,
            )

            # Signal to frontend that budget recovery is available
            if workflow_status == "budget_exhausted":
                state_data["budget_recovery_available"] = True

            await manager.send_event(
                client_id=client_id,
                event_type="plan.state",
                workflow_id=workflow_id,
                data=state_data,
            )

            # Re-emit the current interrupt prompt if the workflow is paused
            idata = await self._extract_interrupt_from_state(engine, config)
            if idata:
                idata.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, idata)
        except Exception as e:
            logger.error(f"Plan reconnect failed: {e}", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to reconnect plan session: {e}",
                "ENGINE_ERROR",
            )

    async def handle_step_forward(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.step.forward — advance to the next sequential phase.

        Only works when the current phase is complete (not running or at
        an interrupt). Sets current_phase to the next uncompleted phase
        and invokes the graph from there.
        """
        try:
            validated = PlanStepForwardPayload(**payload)
        except ValidationError as e:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Invalid plan.step.forward payload: {e.errors()}",
                "VALIDATION_ERROR",
            )
            return

        session = self.get_session(validated.session_id)
        if not session:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"No active plan session: {validated.session_id}",
                "SESSION_NOT_FOUND",
            )
            return

        engine = session["engine"]
        config: RunnableConfig = session["config"]
        state = await engine.get_workflow_state(config)
        if state is None:
            await self._emit_plan_error(
                client_id,
                workflow_id,
                "No workflow state",
                "STATE_NOT_FOUND",
            )
            return

        completed = self._normalize_completed_phases(state)
        phase_order = list(self._PHASE_ORDER)

        # Find the first uncompleted phase after all completed ones
        next_phase: str | None = None
        for p in phase_order:
            if not completed.get(p):
                next_phase = p
                break

        if next_phase is None or next_phase == "context" and not completed.get("context"):
            # All phases complete or nothing started yet
            await self._emit_plan_error(
                client_id,
                workflow_id,
                "No next phase available",
                "NO_NEXT_PHASE",
            )
            return

        _debug_log(
            "PLAN_STEP_FORWARD",
            client_id=client_id,
            session_id=validated.session_id,
            target_phase=next_phase,
        )

        try:
            result = await engine.restart_from_phase(next_phase, config)
            session["running_task"] = None
            idata = await self._extract_interrupt_from_state(engine, config)
            if idata:
                idata.setdefault("session_id", validated.session_id)
                await self._emit_phase_prompt(client_id, workflow_id, idata)
            elif await self._check_and_emit_error(result, client_id, workflow_id, validated.session_id):
                return
        except Exception as e:
            session["running_task"] = None
            logger.error(f"Plan step forward failed: {e}", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Failed to step forward: {e}",
                "ENGINE_ERROR",
            )

    async def handle_step_backward(self, client_id: str, workflow_id: str, payload: Dict[str, Any]) -> None:
        """Handle plan.step.backward — navigate to a previous phase.

        Delegates to handle_navigate with backward-specific logic.
        Emits plan.cascade.confirm if confirm_cascade is False.
        """
        await self.handle_navigate(client_id, workflow_id, payload)

    # ── Main dispatcher ────────────────────────────────────────

    async def dispatch(
        self,
        client_id: str,
        msg_type: str,
        payload: Dict[str, Any],
        workflow_id: Optional[str] = None,
    ) -> None:
        """Route plan.* messages to the appropriate handler.

        Requirements: 20.1, 20.2
        """
        if not workflow_id:
            workflow_id = manager.create_workflow(client_id=client_id, workflow_type="plan")

        try:
            if msg_type == "plan.start":
                await self.handle_start(client_id, workflow_id, payload)
            elif msg_type == "plan.phase.input":
                await self.handle_phase_input(client_id, workflow_id, payload)
            elif msg_type == "plan.navigate":
                await self.handle_navigate(client_id, workflow_id, payload)
            elif msg_type == "plan.resume":
                await self.handle_resume(client_id, workflow_id, payload)
            elif msg_type == "plan.pause":
                await self.handle_pause(client_id, workflow_id, payload)
            elif msg_type == "plan.retry":
                await self.handle_retry(client_id, workflow_id, payload)
            elif msg_type == "plan.step.forward":
                await self.handle_step_forward(client_id, workflow_id, payload)
            elif msg_type == "plan.step.backward":
                await self.handle_step_backward(client_id, workflow_id, payload)
            elif msg_type == "plan.reconnect":
                await self.handle_reconnect(client_id, workflow_id, payload)
            else:
                await self._emit_plan_error(
                    client_id,
                    workflow_id,
                    f"Unknown plan message type: {msg_type}",
                    "UNKNOWN_PLAN_MESSAGE",
                )
        except Exception as e:
            logger.error(f"Plan dispatch error: {e}", exc_info=True)
            await self._emit_plan_error(
                client_id,
                workflow_id,
                f"Internal error: {e}",
                "INTERNAL_ERROR",
            )


# ── Singleton + backward-compatible aliases ────────────────────────────

plan_dispatcher = PlanDispatcher()

# Primary entry point (used by dispatcher.py)
dispatch_plan_message = plan_dispatcher.dispatch

# Individual handlers (used by tests)
handle_plan_start = plan_dispatcher.handle_start
handle_plan_phase_input = plan_dispatcher.handle_phase_input
handle_plan_navigate = plan_dispatcher.handle_navigate
handle_plan_resume = plan_dispatcher.handle_resume
handle_plan_pause = plan_dispatcher.handle_pause
handle_plan_retry = plan_dispatcher.handle_retry
handle_plan_reconnect = plan_dispatcher.handle_reconnect
handle_plan_step_forward = plan_dispatcher.handle_step_forward
handle_plan_step_backward = plan_dispatcher.handle_step_backward

# Internal helpers (used by tests)
_sessions = plan_dispatcher._sessions
_get_session = plan_dispatcher.get_session
_cancel_running_task = plan_dispatcher._cancel_running_task
_validate_session_owner = plan_dispatcher._validate_session_owner
_emit_phase_progress = PlanDispatcher._emit_phase_progress
_emit_plan_error = PlanDispatcher._emit_plan_error
_emit_phase_prompt = PlanDispatcher._emit_phase_prompt


def _register_session(
    session_id: str,
    engine: PlanEngine,
    config: RunnableConfig,
    *args: str,
) -> None:
    """Register a session using either the current or legacy helper signature."""
    if len(args) == 2:
        client_id, workflow_id = args
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = str(configurable.get("thread_id") or f"plan-{session_id}")
        user_id = client_id
    elif len(args) == 4:
        thread_id, user_id, client_id, workflow_id = args
    else:
        raise TypeError(
            "_register_session expected either "
            "(session_id, engine, config, client_id, workflow_id) or "
            "(session_id, engine, config, thread_id, user_id, client_id, workflow_id)"
        )

    plan_dispatcher._register_session(
        session_id,
        engine,
        config,
        thread_id,
        user_id,
        client_id,
        workflow_id,
    )
