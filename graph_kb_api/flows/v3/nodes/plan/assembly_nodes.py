"""Assembly subgraph nodes for the /plan command.

CompletenessNode, TemplateNode, GenerateNode, ConsistencyNode, AssembleNode,
ValidateNode, AssemblyApprovalNode, FinalizeNode.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, cast

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
    from graph_kb_api.flows.v3.state.workflow_state import UnifiedSpecState

from langchain.messages import AIMessage
from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.core.llm import LLMService
from graph_kb_api.database.base import get_session as get_db_session
from graph_kb_api.database.plan_repositories import PlanSessionRepository
from graph_kb_api.flows.v3.agents import AgentResult
from graph_kb_api.flows.v3.agents.consistency_checker_agent import ConsistencyCheckerAgent
from graph_kb_api.flows.v3.agents.document_assembly_agent import DocumentAssemblyAgent
from graph_kb_api.flows.v3.agents.personas.prompt_manager import get_agent_prompt_manager
from graph_kb_api.flows.v3.agents.validation_agent import ValidationAgent
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import AgentTask, ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.nodes.plan.base_approval_node import BaseApprovalNode
from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard, BudgetState
from graph_kb_api.flows.v3.state import GenerateData, PlanData
from graph_kb_api.flows.v3.state.plan_state import (
    ASSEMBLY_PROGRESS,
    ArtifactRef,
    AssemblySubgraphState,
    DocumentManifest,
    InterruptOption,
    TransitionEntry,
    WorkflowError,
)
from graph_kb_api.flows.v3.state.workflow_state import (
    CompletenessData,
    ContextData,
    OrchestrateData,
    ResearchData,
)
from graph_kb_api.flows.v3.utils.json_parsing import parse_json_from_llm
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator, truncate_to_tokens
from graph_kb_api.flows.v3.utils.dedup_directives import validate_dedup_directives, CompositionReviewResponse
from graph_kb_api.websocket.plan_events import emit_complete, emit_error, emit_phase_complete, emit_phase_progress

logger = logging.getLogger(__name__)


def _unwrap_json_document(content: str) -> str:
    """Extract markdown from a JSON wrapper if the LLM returned JSON instead of raw markdown.

    Some LLMs wrap the assembled document in a JSON object like:
    {"assembled_document": "# Title...", "sections_included": [...], ...}

    This detects that pattern and extracts just the markdown content.
    """
    if not isinstance(content, str) or not content.strip().startswith("{"):
        return content
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "assembled_document" in parsed:
            doc = parsed["assembled_document"]
            if isinstance(doc, str) and len(doc) > 50:
                logger.info("_unwrap_json_document: extracted assembled_document from JSON wrapper")
                return doc
    except (json.JSONDecodeError, ValueError):
        pass
    return content


class CompletenessNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Checks completeness of generated content before assembly.

    Verifies all required task outputs are present and complete
    before proceeding to document assembly.

    Requirements: 23.1, 23.2
    """

    def __init__(self) -> None:
        super().__init__(node_name="completeness")
        self.phase = "assembly"
        self.step_name = "completeness"
        self.step_progress = ASSEMBLY_PROGRESS["completeness"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        await self._emit_progress(ctx, "completeness", 0.0, "Checking completeness of task outputs...")

        orchestrate: OrchestrateData = state.get("orchestrate", {})
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        task_results = orchestrate.get("task_results", [])
        expected_tasks = planning.get("task_dag", {}).get("tasks", [])

        completed_task_ids = {t.get("id") for t in task_results if t.get("status") == "done"}
        expected_task_ids = {t.get("id") for t in expected_tasks}

        missing_tasks = expected_task_ids - completed_task_ids
        completeness_score = len(completed_task_ids) / len(expected_task_ids) if expected_task_ids else 1.0

        is_complete: bool = len(missing_tasks) == 0

        # Manifest-aware completeness check (Step 15)
        manifest: DocumentManifest | None = state.get("document_manifest")
        manifest_issues: list[dict[str, Any]] = []
        if manifest:
            entries = manifest.get("entries", [])
            failed_entries = [e for e in entries if e.get("status") in ("failed", "error")]
            for entry in failed_entries:
                manifest_issues.append(
                    {
                        "task_id": entry.get("task_id", ""),
                        "spec_section": entry.get("spec_section", ""),
                        "status": entry.get("status", ""),
                        "error": entry.get("error_message", ""),
                    }
                )

            # Cross-reference manifest entries against document_section_index
            doc_index = context.get("document_section_index", [])
            if doc_index:
                primary_entries = [d for d in doc_index if d.get("role") == "primary"]
                if primary_entries:
                    covered_sections = {e.get("spec_section", "") for e in entries}
                    all_spec_headings = {s["heading"] for s in primary_entries[0].get("sections", [])}
                    uncovered = all_spec_headings - covered_sections
                    for heading in uncovered:
                        manifest_issues.append(
                            {
                                "task_id": "",
                                "spec_section": heading,
                                "status": "missing",
                                "error": "No deliverable produced for this spec section",
                            }
                        )

            if manifest_issues:
                is_complete = False
                completeness_score = min(completeness_score, 0.7)

        return NodeExecutionResult.success(
            output={
                "completeness": {
                    "completeness_check": {
                        "is_complete": is_complete,
                        "completeness_score": completeness_score,
                        "completed_tasks": list(completed_task_ids),
                        "missing_tasks": list(missing_tasks),
                        "total_expected": len(expected_task_ids),
                        "total_completed": len(completed_task_ids),
                        "manifest_issues": manifest_issues,
                    },
                    "complete": is_complete,
                }
            }
        )


class TemplateNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Derives document section names from the planning task DAG.

    Instead of a hardcoded template, sections are determined dynamically
    from the tasks decomposed during the planning phase.
    """

    def __init__(self) -> None:
        super().__init__(node_name="template")
        self.phase = "assembly"
        self.step_name = "template"
        self.step_progress = ASSEMBLY_PROGRESS["template"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        await self._emit_progress(ctx, "template", 0.15, "Deriving document sections from plan...")

        context: ContextData = state.get("context", {})
        planning: PlanData = state.get("plan", {})

        spec_name = context.get("spec_name", "Feature Specification")

        # Derive section names from the task DAG produced by DecomposeNode
        task_dag = planning.get("task_dag", {})
        tasks = task_dag.get("tasks", [])
        section_names = [t["name"] for t in tasks if t.get("name")]

        if not section_names:
            logger.warning("TemplateNode: no task names found in task_dag — assembly will have no sections")

        phases_count = len(planning.get("roadmap", {}).get("phases", []))

        return NodeExecutionResult.success(
            output={
                "generate": {
                    "template": {
                        "variables": section_names,
                        "spec_name": spec_name,
                        "phases_count": phases_count,
                    }
                }
            }
        )


class GenerateNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Generates document sections or polishes existing deliverables.

    When a document_manifest exists with "reviewed" entries, performs a polish
    pass: loads deliverables from blob, applies composition review fixes, and
    promotes entries to "final" status.

    Otherwise, falls back to the original LLM generation behavior.
    """

    def __init__(self) -> None:
        super().__init__(node_name="generate")
        self.phase = "assembly"
        self.step_name = "generate"
        self.step_progress = ASSEMBLY_PROGRESS["generate"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget

        context: ContextData = state.get("context", {})
        research: ResearchData = state.get("research", {})
        orchestrate: OrchestrateData = state.get("orchestrate", {})
        generate_data: GenerateData = state.get("generate", {})
        completeness: CompletenessData = state.get("completeness", {})

        manifest: DocumentManifest | None = state.get("document_manifest")

        # Polish pass: promote manifest entries to "final" (Step 17)
        if manifest and manifest.get("entries"):
            return await self._polish_pass(state, config, manifest, completeness, ctx.artifact_service, budget)

        # Original generation behavior (backward compat / no-manifest path)
        template_vars = generate_data.get("template", {}).get("variables", [])
        spec_name = context.get("spec_name", "Feature")

        logger.info(
            f"[GenerateNode] template_vars={template_vars}, "
            f"llm={'present' if ctx.llm else 'MISSING'}, "
            f"budget_remaining={budget.get('remaining_llm_calls', '?')}, "
            f"orchestrate_task_results={len(orchestrate.get('task_results', []))}"
        )

        BudgetGuard.check(budget)

        llm = ctx.require_llm

        sections: Dict[str, str] = {}
        llm_calls = 0

        for idx, var in enumerate(template_vars):
            await self._emit_progress(
                ctx, "generate",
                0.30 + (0.25 * (idx + 1) / len(template_vars)),
                f"Generating section '{var}' ({idx + 1}/{len(template_vars)})...",
            )
            try:
                prompt: str = self._build_section_prompt(var, spec_name, context, research, orchestrate)
                response: AIMessage = await llm.ainvoke(prompt)
                raw_content = response.content if hasattr(response, "content") else str(response)
                content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
                sections[var] = content
                llm_calls += 1
            except Exception as e:
                logger.warning("GenerateNode failed for section %s: %s", var, e)
                sections[var] = f"*Section '{var}' generation pending*"

        artifacts_output: Dict[str, Any] = {}
        if ctx.artifact_service and sections:
            ref = await ctx.artifact_service.store(
                "generate",
                "sections.json",
                json.dumps(sections, indent=2),
                f"Generated sections for {spec_name}",
            )
            artifacts_output["generate.sections"] = ref

        new_budget = self._decrement_budget(budget, json.dumps(sections, default=str), llm_calls=llm_calls)

        return NodeExecutionResult.success(
            output={
                "generate": {**generate_data, "sections": sections},
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )

    def _build_section_prompt(
        self,
        section_name: str,
        spec_name: str,
        context: ContextData,
        research: ResearchData,
        orchestrate: OrchestrateData,
    ) -> str:
        # Exclude large document arrays from JSON dump so the budget is spent on meaningful context fields
        # rather than being consumed by raw document content. This prevents the literal HTML blobs
        # in reference_documents from corrupting the JSON prompt.
        lightweight_context = {
            k: v
            for k, v in context.items()
            if k not in ("uploaded_document_contents", "document_section_index", "reference_documents")
        }
        context_summary: str = json.dumps(lightweight_context, indent=2, default=str)

        # Append document section TOC separately (compact, high-signal).
        section_index = context.get("document_section_index", [])
        if section_index:
            toc_lines = []
            for doc in section_index:
                role_label = doc.get("role", "supporting")
                toc_lines.append(f"\n### {doc['filename']} ({role_label})")
                for sec in doc.get("sections", []):
                    toc_lines.append(f"- {sec['heading']}")
            context_summary += "\n\n## Document Sections\n" + "\n".join(toc_lines)

        findings_summary: str = json.dumps(research.get("findings", {}), indent=2, default=str)
        task_outputs_summary: str = json.dumps(orchestrate.get("task_results", []), indent=2, default=str)

        return get_agent_prompt_manager().render_prompt(
            "assembly_section",
            subdir="nodes",
            section_name=section_name,
            spec_name=spec_name,
            context_summary=context_summary,
            findings_summary=findings_summary,
            task_outputs_summary=task_outputs_summary,
        )

    async def _polish_pass(
        self,
        state: AssemblySubgraphState,
        config: RunnableConfig,
        manifest: DocumentManifest,
        completeness: CompletenessData,
        artifact_svc: ArtifactService | None,
        budget: BudgetState,
    ) -> NodeExecutionResult:
        """Polish existing deliverables: promote reviewed entries to final.

        When composition review found issues, applies targeted fixes via LLM.
        Otherwise, simply promotes entries to "final" status.
        """
        session_id = state.get("session_id", "")
        client_id = cast(ThreadConfigurable, config.get("configurable", {})).get("client_id")

        composition_review = completeness.get("composition_review")
        review_issues = composition_review.get("issues", []) if composition_review else []

        entries: list[dict[str, Any]] = [dict(e) for e in manifest["entries"]]

        # Apply dedup directives: remove entries flagged as duplicates,
        # keeping only the canonical section for each duplicated topic.
        dedup_directives = composition_review.get("dedup_directives", []) if composition_review else []
        if dedup_directives:
            remove_task_ids: set[str] = set()
            for directive in dedup_directives:
                for dup_id in directive.get("duplicate_in", []):
                    remove_task_ids.add(dup_id)
            if remove_task_ids:
                before_count = len(entries)
                entries = [e for e in entries if e.get("task_id") not in remove_task_ids]
                logger.info(
                    "GenerateNode: dedup removed %d duplicate entries (kept %d)",
                    before_count - len(entries),
                    len(entries),
                )

        llm_calls = 0
        tokens_used = 0
        polished_count = 0

        for idx, entry in enumerate(entries):
            if entry.get("status") not in ("reviewed", "draft"):
                continue

            try:
                await emit_phase_progress(
                    session_id=session_id,
                    phase="assembly",
                    step="generate",
                    message=f"Polishing '{entry.get('spec_section', '')}' ({idx + 1}/{len(entries)})...",
                    progress_pct=0.30 + (0.25 * (idx + 1) / len(entries)),
                    client_id=client_id,
                )
            except Exception:
                pass

            ref: ArtifactRef | None = entry.get("artifact_ref")
            if ref and artifact_svc:
                try:
                    content = await artifact_svc.retrieve(ref)
                    # Apply LLM polish if issues exist and LLM is available
                    if review_issues and content:
                        llm = cast(ThreadConfigurable, config.get("configurable", {})).get("llm")
                        if llm:
                            relevant_issues = [
                                i for i in review_issues if entry.get("task_id") in i.get("affected_task_ids", [])
                            ]
                            if relevant_issues:
                                polish_prompt = (
                                    f"Polish this document section to fix the following issues:\n"
                                    f"{json.dumps(relevant_issues, indent=2)}\n\n"
                                    f"## Document\n\n{content}\n\n"
                                    f"Return the polished document. Keep all existing content, "
                                    f"just fix the identified issues."
                                )
                                response: AIMessage = await llm.ainvoke(polish_prompt)
                                polished = response.content if hasattr(response, "content") else str(response)
                                polished = str(polished) if not isinstance(polished, str) else polished
                                content = polished
                                llm_calls += 1

                    # Re-store polished content at the same path
                    if content:
                        # Extract the key within the deliverables collection
                        original_key = ref.get("key", f"deliverables/{entry['task_id']}/polished.md")
                        deliverable_key = (
                            original_key.split("/", 1)[1] if "/" in original_key else f"{entry['task_id']}/polished.md"
                        )
                        await artifact_svc.store(
                            "deliverables",
                            deliverable_key,
                            content,
                            f"Polished deliverable for: {entry.get('spec_section', '')}",
                        )
                        tokens_used += get_token_estimator().count_tokens(content)

                    entries[idx] = {
                        **entry,
                        "status": "final",
                        "composed_at": datetime.now(UTC).isoformat(),
                    }
                    polished_count += 1
                except Exception as e:
                    logger.warning(f"GenerateNode polish failed for {entry.get('task_id')}: {e}")
                    entries[idx] = {**entry, "status": "final", "composed_at": datetime.now(UTC).isoformat()}

        new_budget = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

        updated_manifest = {
            **manifest,
            "entries": entries,
            "total_documents": len(entries),
            "total_tokens": sum(e.get("token_count", 0) for e in entries),
        }

        logger.info(f"GenerateNode polish pass: {polished_count}/{len(entries)} entries promoted to final")

        return NodeExecutionResult.success(
            output={
                "document_manifest": updated_manifest,
                "budget": new_budget,
            }
        )


class ConsistencyNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Checks consistency of generated sections via LLM.

    Uses ConsistencyCheckerAgent for semantic cross-section validation.
    """

    def __init__(self) -> None:
        super().__init__(node_name="consistency")
        self.phase = "assembly"
        self.step_name = "consistency"
        self.step_progress = ASSEMBLY_PROGRESS["consistency"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget

        manifest: DocumentManifest | None = state.get("document_manifest")
        if manifest:
            logger.info(
                "ConsistencyNode: skipping semantic check for multi-document manifest"
                " (handled by CompositionReviewNode)"
            )
            return NodeExecutionResult.success(output={"completeness": state.get("completeness", {})})

        generate_data: GenerateData = state.get("generate", {})
        sections = generate_data.get("sections", {})

        BudgetGuard.check(budget)

        consistency_issues: list[dict[str, Any]] = []

        await self._emit_progress(ctx, "consistency", 0.60, "Running consistency checks across sections...")

        agent = ConsistencyCheckerAgent()

        agent_task: AgentTask = {
            "description": "Consistency check across sections",
            "task_id": f"consistency_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "context": {
                "sections": sections,
                "plan_context": state.get("context", {}),
            },
        }
        agent_state = {"completed_sections": sections}

        result: AgentResult = await agent.execute(task=agent_task, state=agent_state, workflow_context=ctx.workflow_context)

        # Convert agent issues to node format
        for issue in result.get("consistency_issues", []):
            consistency_issues.append(
                {
                    "section": issue.get("affected_sections", ["unknown"])[0]
                    if issue.get("affected_sections")
                    else "unknown",
                    "issue": issue.get("description", issue.get("issue_type", "Consistency issue")),
                    "severity": issue.get("severity", "warning"),
                    "issue_type": issue.get("issue_type", "unknown"),
                    "source": "llm_semantic",
                }
            )

        llm_calls = 1

        logger.info(f"ConsistencyNode: LLM semantic check found {len(consistency_issues)} issues")

        is_consistent: bool = len([i for i in consistency_issues if i.get("severity") == "error"]) == 0

        new_budget = self._decrement_budget(budget, str(result))

        # Get current iteration count for loop guard (read by _route_after_consistency)
        completeness: CompletenessData = state.get("completeness", {})
        current_iterations: int = completeness.get("consistency_iterations", 0)

        # Store consistency report via ArtifactService (GAP 12a)
        artifacts_output: Dict[str, Any] = {}
        report = {
            "is_consistent": is_consistent,
            "issues": consistency_issues,
            "sections_checked": list(sections.keys()),
            "iteration": current_iterations + 1,
            "source": "llm_semantic" if llm_calls > 0 else "deterministic",
        }
        if ctx.artifact_service:
            try:
                ref: ArtifactRef = await ctx.artifact_service.store(
                    "assembly",
                    "consistency_report.json",
                    json.dumps(report, indent=2),
                    f"Consistency report iteration {current_iterations + 1}: {len(consistency_issues)} issues",
                )
                artifacts_output["assembly.consistency_report"] = ref
            except Exception:
                pass  # best-effort

        return NodeExecutionResult.success(
            output={
                "completeness": {
                    **completeness,
                    "consistency_issues": consistency_issues,
                    "consistency_iterations": current_iterations + 1,
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )


class CompositionReviewNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Reviews the holistic quality of the deliverable document suite.

    Hydrates all deliverable documents from blob storage, token-budgets
    them, and calls the LLM with a composition review prompt that checks
    for cross-document redundancy, conflicting terminology, missing
    cross-references, inconsistent formatting, and coverage gaps.

    Stores the review result in state with an overall score and issues list.
    """

    def __init__(self) -> None:
        super().__init__(node_name="composition_review")
        self.phase = "assembly"
        self.step_name = "composition_review"
        self.step_progress = ASSEMBLY_PROGRESS["composition_review"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget

        await self._emit_progress(ctx, "composition_review", 0.60, "Reviewing document suite composition...")

        manifest: DocumentManifest | None = state.get("document_manifest")

        # If no manifest, skip composition review (legacy path)
        if not manifest or not manifest.get("entries"):
            logger.info("CompositionReviewNode: no manifest entries — skipping review")
            return NodeExecutionResult.success(
                output={"completeness": {**state.get("completeness", {}), "composition_review": None}}
            )

        # Hydrate deliverable content from blob storage
        max_review_tokens = 30000
        entries = manifest.get("entries", [])
        deliverables: list[dict[str, str]] = []  # [{task_id, content}]
        tokens_budgeted = 0

        if ctx.artifact_service:
            total_tokens = sum(e.get("token_count", 0) for e in entries)
            for entry in entries:
                if entry.get("status") in ("failed", "error"):
                    continue
                ref: ArtifactRef = entry.get("artifact_ref")
                if not ref:
                    continue

                # Proportional token budget per document
                if total_tokens > 0:
                    doc_budget = int(max_review_tokens * entry.get("token_count", 0) / total_tokens)
                else:
                    doc_budget = max_review_tokens // max(len(entries), 1)

                try:
                    content = await ctx.artifact_service.retrieve(ref)
                    if content and get_token_estimator().count_tokens(content) > doc_budget:
                        # Truncate to token budget using tiktoken
                        content = truncate_to_tokens(content, doc_budget)
                    deliverables.append({"task_id": entry["task_id"], "content": content or ""})
                    tokens_budgeted += get_token_estimator().count_tokens(content) if content else 0
                except Exception as e:
                    logger.warning(f"CompositionReviewNode: failed to load {entry['task_id']}: {e}")

        # Build composition review prompt
        review_prompt = self._build_review_prompt(manifest, deliverables)
        composition_result: dict[str, Any] = {
            "overall_score": 1.0,
            "summary": "Composition review skipped — no LLM available.",
            "issues": [],
            "needs_re_orchestrate": False,
        }
        llm_calls = 0

        if ctx.llm and deliverables:
            try:
                # Use structured output to guarantee field names and types.
                # with_structured_output uses OpenAI's response_format=json_schema
                # which enforces the schema at the token generation level.
                structured_llm = ctx.llm.with_structured_output(CompositionReviewResponse)
                parsed_response: CompositionReviewResponse = await structured_llm.ainvoke(review_prompt)

                composition_result = {
                    "overall_score": max(0.0, min(1.0, parsed_response.overall_score)),
                    "summary": parsed_response.summary,
                    "issues": [issue.model_dump() for issue in parsed_response.issues],
                    "needs_re_orchestrate": parsed_response.needs_re_orchestrate,
                }

                # Validate dedup directives against manifest task IDs
                raw_directives = [d.model_dump() for d in parsed_response.dedup_directives]
                if raw_directives:
                    manifest_task_ids = {
                        e.get("task_id", "")
                        for e in (manifest.get("entries", []) if manifest else [])
                        if e.get("task_id")
                    }
                    # Build section-title-to-task-id lookup so the validator
                    # can resolve LLM responses that use titles instead of IDs.
                    section_to_task_id: dict[str, str] = {}
                    for entry in manifest.get("entries", []) if manifest else []:
                        tid = entry.get("task_id", "")
                        if tid:
                            section_to_task_id[tid] = tid  # identity for task IDs
                            spec_sec = entry.get("spec_section", "")
                            if spec_sec:
                                section_to_task_id[spec_sec] = tid
                            name = entry.get("name", "")
                            if name:
                                section_to_task_id[name] = tid
                    composition_result["dedup_directives"] = validate_dedup_directives(
                        raw_directives, manifest_task_ids, section_to_task_id
                    )
                else:
                    composition_result["dedup_directives"] = []

                llm_calls = 1
            except Exception as e:
                logger.warning(f"CompositionReviewNode: structured output failed, falling back to raw parse: {e}")
                # Fallback: raw ainvoke + parse_json_from_llm
                try:
                    response: AIMessage = await ctx.llm.ainvoke(review_prompt)
                    raw = response.content if hasattr(response, "content") else str(response)
                    content_str = str(raw) if not isinstance(raw, str) else raw

                    parsed = parse_json_from_llm(content_str)
                    if isinstance(parsed, dict):
                        composition_result = {
                            "overall_score": max(0.0, min(1.0, float(parsed.get("overall_score", 0.5)))),
                            "summary": parsed.get("summary", ""),
                            "issues": parsed.get("issues", []),
                            "needs_re_orchestrate": bool(parsed.get("needs_re_orchestrate", False)),
                        }

                        raw_directives = parsed.get("dedup_directives", [])
                        if raw_directives and isinstance(raw_directives, list):
                            manifest_task_ids = {
                                e.get("task_id", "")
                                for e in (manifest.get("entries", []) if manifest else [])
                                if e.get("task_id")
                            }
                            section_to_task_id = {}
                            for entry in manifest.get("entries", []) if manifest else []:
                                tid = entry.get("task_id", "")
                                if tid:
                                    section_to_task_id[tid] = tid
                                    spec_sec = entry.get("spec_section", "")
                                    if spec_sec:
                                        section_to_task_id[spec_sec] = tid
                                    name = entry.get("name", "")
                                    if name:
                                        section_to_task_id[name] = tid
                            composition_result["dedup_directives"] = validate_dedup_directives(
                                raw_directives, manifest_task_ids, section_to_task_id
                            )
                        else:
                            composition_result["dedup_directives"] = []

                    llm_calls = 1
                except Exception as fallback_err:
                    logger.warning(f"CompositionReviewNode: LLM review failed: {fallback_err}")

        # Derive re_execute_task_ids from critical issues
        re_execute_task_ids: list[str] = []
        if composition_result.get("needs_re_orchestrate"):
            for issue in composition_result.get("issues", []):
                if issue.get("severity") in ("critical", "major") and issue.get("affected_task_ids"):
                    re_execute_task_ids.extend(issue["affected_task_ids"])
            # If no specific tasks identified, don't trigger re-orchestration
            if not re_execute_task_ids:
                composition_result["needs_re_orchestrate"] = False

        new_budget = self._decrement_budget(budget, json.dumps(composition_result, default=str), llm_calls=llm_calls)

        output: dict[str, Any] = {
            "completeness": {
                **state.get("completeness", {}),
                "composition_review": composition_result,
            },
            "budget": new_budget,
        }
        if composition_result.get("needs_re_orchestrate") and re_execute_task_ids:
            output["needs_re_orchestrate"] = True
            output["re_execute_task_ids"] = list(set(re_execute_task_ids))
        else:
            output["needs_re_orchestrate"] = False
            output["re_execute_task_ids"] = []

        return NodeExecutionResult.success(output=output)

    def _build_review_prompt(self, manifest: DocumentManifest, deliverables: list[dict[str, str]]) -> str:
        """Build the LLM composition review prompt."""
        sections: list[str] = []
        for doc in deliverables:
            sections.append(f"\n## Document: {doc['task_id']}\n\n{doc['content']}")

        deliverables_text = "\n".join(sections)
        manifest_summary = json.dumps(
            {
                "spec_name": manifest.get("spec_name", ""),
                "total_documents": manifest.get("total_documents", 0),
                "entries": [
                    {
                        "task_id": e.get("task_id", ""),
                        "spec_section": e.get("spec_section", ""),
                        "status": e.get("status", ""),
                        "token_count": e.get("token_count", 0),
                    }
                    for e in manifest.get("entries", [])
                ],
            },
            indent=2,
        )

        return (
            f"# Composition Review\n\n"
            f"## Document Suite Manifest\n```json\n{manifest_summary}\n```\n\n"
            f"## Deliverable Content (truncated to budget)\n"
            f"{deliverables_text}\n\n"
            f"## Instructions\n\n"
            f"Review the document suite for cross-document redundancy, conflicting terminology, "
            f"missing cross-references, inconsistent formatting, coverage gaps, and failed tasks. "
            f"For each redundancy issue identified, produce a dedup_directive specifying which "
            f"section should be the canonical owner and which sections should replace the "
            f"duplicate content with a cross-reference. "
            f"Return a JSON object with overall_score (0-1), summary, issues list, "
            f"needs_re_orchestrate (bool), recommendations, and dedup_directives."
        )


async def _persist_assembly_completion_to_db(
    session_id: str,
    spec_document_url: str,
) -> None:
    """Persist assembly completion evidence directly to plan_sessions.

    Called at the end of AssembleNode so that if the server dies before the
    parent LangGraph checkpoint is written, reconnect recovery can still detect
    that assembly finished and re-emit plan.complete.  This mirrors the pattern
    used by the orchestrate subgraph for task_results.
    """
    if not session_id:
        return
    try:
        async with get_db_session() as db:
            repo = PlanSessionRepository(db)
            existing = await repo.get(session_id)
            if existing:
                existing_phases = dict(existing.completed_phases or {})
                existing_phases["assembly"] = True
                await repo.update(
                    session_id,
                    completed_phases=existing_phases,
                    spec_document_url=spec_document_url or existing.spec_document_url or "",
                    current_phase="assembly",
                )
    except Exception:
        logger.warning(
            "AssembleNode: failed to persist assembly completion to DB",
            exc_info=True,
        )


class AssembleNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Assembles the final document from generated sections via DocumentAssemblyAgent (LLM).

    Uses DocumentAssemblyAgent for intelligent assembly with transitions.
    """

    def __init__(self) -> None:
        super().__init__(node_name="assemble")
        self.phase = "assembly"
        self.step_name = "assemble"
        self.step_progress = ASSEMBLY_PROGRESS["assemble"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget

        await self._emit_progress(ctx, "assemble", 0.70, "Assembling final document from sections...")

        context: ContextData = state.get("context", {})
        generate_data: GenerateData = state.get("generate", {})
        research: ResearchData = state.get("research", {})

        BudgetGuard.check(budget)

        template = generate_data.get("template", {}).get("content", "")
        sections = generate_data.get("sections", {})
        spec_name = context.get("spec_name", "Feature Specification")

        manifest = state.get("document_manifest")

        artifacts_output: Dict[str, Any] = {}
        manifest_output: Dict[str, Any] = {}
        spec_document_path = ""
        flow_score = 0.5
        document = ""
        llm_calls = 0
        tokens_used = 0

        # Multi-document path (Step 18)
        if manifest and manifest.get("entries"):
            # Hydrate deliverable sections from blob storage for LLM assembly
            hydrated_sections: Dict[str, str] = {}
            if ctx.artifact_service:
                seen_sections: set[str] = set()
                for entry in manifest.get("entries", []):
                    if entry.get("status") in ("failed", "error"):
                        continue
                    ref: ArtifactRef | None = entry.get("artifact_ref")
                    if not ref:
                        continue
                    section_key = entry.get("spec_section", entry.get("task_id", ""))
                    # Deduplicate: skip if we already have this section
                    if section_key in seen_sections:
                        continue
                    seen_sections.add(section_key)
                    try:
                        content = await ctx.artifact_service.retrieve(ref)
                        if content:
                            # Strip YAML frontmatter from deliverable content
                            content = self._strip_frontmatter(content)
                            hydrated_sections[section_key] = content
                    except Exception as e:
                        logger.warning("AssembleNode: failed to hydrate %s: %s", entry.get("task_id"), e)

            # Run LLM assembly to produce a single cohesive document
            workflow_context: WorkflowContext | None = ctx.workflow_context
            assembled_document = ""
            flow_score = 0.5

            # Sort sections by dependency order using topological sort
            planning: PlanData = state.get("plan", {})
            task_dag = planning.get("task_dag", {})
            sorted_keys = self._topological_sort_sections(hydrated_sections, task_dag)
            sorted_sections: Dict[str, str] = {k: hydrated_sections[k] for k in sorted_keys if k in hydrated_sections}

            # Attempt lightweight LLM executive summary pass
            executive_summary = ""
            transitions: list[str] = []
            if hydrated_sections and workflow_context and sorted_keys:
                try:
                    executive_summary, transitions = await self._generate_executive_summary(
                        sorted_keys, hydrated_sections, spec_name, workflow_context,
                    )
                    logger.info("AssembleNode: executive summary generated (%d transitions)", len(transitions))
                except Exception as e:
                    logger.warning("AssembleNode: executive summary generation failed, skipping: %s", e)
                    executive_summary = ""
                    transitions = []

            if hydrated_sections and workflow_context:
                try:
                    BudgetGuard.check(budget)
                    agent = DocumentAssemblyAgent()
                    toc = self._generate_toc(sorted_keys) if sorted_keys else ""
                    agent_task: AgentTask = {
                        "description": f"Assemble document: {spec_name}",
                        "task_id": f"assembly_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
                        "context": {
                            "sections": sorted_sections,
                            "spec_name": spec_name,
                            "table_of_contents": toc,
                            "executive_summary": executive_summary,
                            "transitions": transitions,
                            "user_explanation": context.get("user_explanation", ""),
                            "constraints": context.get("constraints", {}),
                            "research_summary": research.get("findings", {}).get("summary", ""),
                            "key_insights": research.get("findings", {}).get("key_insights", []),
                        },
                    }
                    try:
                        await emit_phase_progress(
                            session_id=ctx.session_id,
                            phase="assembly",
                            step="assemble",
                            message="Running LLM assembly to produce final document...",
                            progress_pct=0.75,
                            client_id=ctx.client_id,
                        )
                    except Exception:
                        pass

                    result: AgentResult = await agent.execute(
                        task=agent_task,
                        state=cast("UnifiedSpecState", {}),
                        workflow_context=workflow_context,
                    )
                    output_data = result.get("output", {})
                    if isinstance(output_data, dict):
                        assembled_document = output_data.get("assembled_document", "")
                        flow_score = output_data.get("flow_score", 0.5)
                    else:
                        assembled_document = result.get("assembled_document", "")
                        flow_score = result.get("flow_score", 0.5)

                    # Safety: if assembled_document is a JSON wrapper, extract the markdown
                    assembled_document = _unwrap_json_document(assembled_document)
                    llm_calls = 1
                    tokens_used = get_token_estimator().count_tokens(assembled_document) if assembled_document else 0
                    logger.info("AssembleNode: LLM assembly completed with flow_score=%.2f", flow_score)
                except Exception as e:
                    logger.warning("AssembleNode: LLM assembly failed, falling back to concatenation: %s", e)
                    # Fallback: concatenate sections in topological order with exec summary + transitions
                    assembled_document = self._build_fallback_document(
                        spec_name, sorted_keys, hydrated_sections, executive_summary, transitions,
                    )

            if not assembled_document and hydrated_sections:
                # Fallback if no workflow_context — use topological order with exec summary + transitions
                assembled_document = self._build_fallback_document(
                    spec_name, sorted_keys, hydrated_sections, executive_summary, transitions,
                )

            spec_document_path = ""
            if ctx.artifact_service:
                # Store assembled document
                if assembled_document:
                    spec_ref = await ctx.artifact_service.store(
                        "output",
                        "spec.md",
                        assembled_document,
                        f"Assembled specification for {spec_name}",
                        content_type="text/markdown",
                    )
                    artifacts_output["output.spec"] = spec_ref
                    spec_document_path = spec_ref.get("key", "") if isinstance(spec_ref, dict) else ""

                # Store index and manifest
                composed_index = self._build_composed_index(manifest, spec_name, sections)
                index_ref = await ctx.artifact_service.store(
                    "output",
                    "index.md",
                    composed_index,
                    f"Composed document index for {spec_name}",
                )
                artifacts_output["output.index"] = index_ref

                manifest = {**manifest, "composed_index_ref": index_ref}
                manifest_output = {"document_manifest": manifest}

                await ctx.artifact_service.store(
                    "output",
                    "manifest.json",
                    json.dumps(manifest, indent=2, default=str),
                    f"Document manifest for {spec_name}",
                )

            new_budget = self._decrement_budget(budget, assembled_document if assembled_document else "", llm_calls=llm_calls)
            await _persist_assembly_completion_to_db(ctx.session_id, spec_document_path)
            return NodeExecutionResult.success(
                output={
                    "generate": {**generate_data, "spec_document_path": spec_document_path, "flow_score": flow_score},
                    "artifacts": artifacts_output,
                    "budget": new_budget,
                    **manifest_output,
                }
            )

        # Legacy generation path
        llm = ctx.require_llm

        agent = DocumentAssemblyAgent()
        workflow_context = ctx.workflow_context

        agent_task: AgentTask = {
            "description": f"Assemble document: {spec_name}",
            "task_id": f"assembly_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "context": {
                "sections": sections,
                "template": template,
                "spec_name": spec_name,
                "user_explanation": context.get("user_explanation", ""),
                "constraints": context.get("constraints", {}),
                "research_summary": research.get("findings", {}).get("summary", ""),
                "key_insights": research.get("findings", {}).get("key_insights", []),
            },
        }

        result: AgentResult = await agent.execute(
            task=agent_task, state=cast("UnifiedSpecState", {}), workflow_context=workflow_context
        )

        output_data = result.get("output", {})
        if isinstance(output_data, dict):
            document = output_data.get("assembled_document", "")
            flow_score = output_data.get("flow_score", 0.5)
        else:
            document = result.get("assembled_document", "")
            flow_score = result.get("flow_score", 0.5)

        # Safety: if document is a JSON wrapper, extract the markdown
        document = _unwrap_json_document(document)
        llm_calls = 1
        tokens_used: int = get_token_estimator().count_tokens(document) if document else 0

        logger.info(f"AssembleNode: LLM assembly completed with flow_score={flow_score:.2f}")

        if ctx.artifact_service:
            ref = await ctx.artifact_service.store(
                "output",
                "spec.md",
                document,
                f"Specification for {spec_name}",
                content_type="text/markdown",
            )
            artifacts_output["output.spec"] = ref
            spec_document_path = ref.key if hasattr(ref, "key") else "output/spec.md"

        new_budget: BudgetState = self._decrement_budget(budget, document if document else "", llm_calls=1)

        output: Dict[str, Any] = {
            "generate": {
                "spec_document_path": spec_document_path,
                "flow_score": flow_score,
            },
            "artifacts": artifacts_output,
            "budget": new_budget,
        }

        await _persist_assembly_completion_to_db(ctx.session_id, spec_document_path)
        return NodeExecutionResult.success(output=output)

    def _build_composed_index(self, manifest: DocumentManifest, spec_name: str, sections: Dict[str, str]) -> str:
        """Build a composed index document with TOC, cross-references, and summary."""
        lines = [f"# Document Suite Index: {spec_name}\n"]
        lines.append(f"**Total Documents:** {manifest.get('total_documents', 0)}")
        lines.append(f"**Total Tokens:** {manifest.get('total_tokens', 0)}\n")

        lines.append("## Table of Contents\n")
        for entry in manifest.get("entries", []):
            status = entry.get("status", "draft")
            section = entry.get("spec_section", "Unknown")
            task_id = entry.get("task_id", "")
            token_count = entry.get("token_count", 0)
            status_icon = "OK" if status == "final" else ("!" if status == "failed" else "~")
            lines.append(f"- [{status_icon}] **{section}** (`{task_id}`) — {token_count} tokens")

        lines.append("\n## Cross-Reference Map\n")
        deps: dict[str, list[str]] = {}
        for entry in manifest.get("entries", []):
            task_id = entry["task_id"]
            for dep in entry.get("dependencies", []):
                deps.setdefault(dep, []).append(task_id)
        if deps:
            for dep, dependents in deps.items():
                lines.append(f"- `{dep}` is referenced by: {', '.join(f'`{d}`' for d in dependents)}")
        else:
            lines.append("No inter-document dependencies detected.")

        failed = [e for e in manifest.get("entries", []) if e.get("status") in ("failed", "error")]
        if failed:
            lines.append("\n## Failed/Error Tasks\n")
            for entry in failed:
                lines.append(
                    f"- **{entry.get('spec_section', 'Unknown')}**"
                    f" ({entry['task_id']}): {entry.get('error_message', 'Unknown error')}"
                )

        return "\n".join(lines)

    @staticmethod
    def _generate_toc(ordered_keys: list[str]) -> str:
        """Generate markdown Table of Contents with anchor links.

        Delegates to the standalone utility for easier testing.
        """
        from graph_kb_api.flows.v3.utils.toc_generation import generate_toc

        return generate_toc(ordered_keys)

    @staticmethod
    def _topological_sort_sections(
        hydrated_sections: dict[str, str],
        task_dag: dict[str, Any],
    ) -> list[str]:
        """Sort section keys by dependency order using Kahn's algorithm.

        Sections with no dependencies (foundations) appear first.
        Sections not in the DAG at all are appended at the end.
        Original dict order is used as stable tiebreaker for sections
        at the same topological level.

        If a cycle is detected (len(result) < len(section_keys) after
        Kahn's completes), logs a warning and falls back to original
        dict iteration order.
        """
        from graph_kb_api.flows.v3.utils.topological_sort import topological_sort_sections

        return topological_sort_sections(hydrated_sections, task_dag)

    @staticmethod
    def _build_fallback_document(
        spec_name: str,
        sorted_keys: list[str],
        hydrated_sections: dict[str, str],
        executive_summary: str = "",
        transitions: list[str] | None = None,
    ) -> str:
        """Build a fallback document with title + exec summary + TOC + sections.

        Used when the full LLM assembly agent fails or when no workflow
        context is available.  If *executive_summary* or *transitions* are
        empty the document degrades gracefully to TOC + sorted sections.
        """
        toc = AssembleNode._generate_toc(sorted_keys) if sorted_keys else ""
        parts: list[str] = [f"# {spec_name}\n"]
        if executive_summary:
            parts.append(f"{executive_summary}\n")
        if toc:
            parts.append(toc)
        for idx, section_name in enumerate(sorted_keys):
            if section_name in hydrated_sections:
                parts.append(f"## {section_name}\n\n{hydrated_sections[section_name]}")
            # Insert transition sentence between adjacent sections
            if transitions and idx < len(transitions) and idx < len(sorted_keys) - 1:
                parts.append(f"_{transitions[idx]}_")
        return "\n\n".join(parts)

    async def _generate_executive_summary(
        self,
        ordered_keys: list[str],
        hydrated_sections: dict[str, str],
        spec_name: str,
        workflow_context: "WorkflowContext",
    ) -> tuple[str, list[str]]:
        """Generate executive summary and transition sentences via lightweight LLM call.

        Sends only section titles + first paragraphs (~2K tokens) to the LLM.
        Returns ``(executive_summary, transition_sentences)`` where
        ``transition_sentences[i]`` bridges section *i* to section *i+1*.
        """
        summaries = self._extract_section_summaries(ordered_keys, hydrated_sections)

        system_prompt = (
            "You are assembling a specification document. Given section titles and their "
            "opening paragraphs, produce:\n"
            "1. An executive summary (3-5 sentences) for the document.\n"
            "2. One transition sentence between each pair of adjacent sections.\n\n"
            "Return JSON: {\"executive_summary\": \"...\", \"transitions\": [\"...\", ...]}\n"
            "The transitions array should have N-1 entries for N sections."
        )

        user_prompt = f"# {spec_name}\n\n{summaries}"

        llm = workflow_context.require_llm
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        data = parse_json_from_llm(str(content))
        return data["executive_summary"], data.get("transitions", [])

    @staticmethod
    def _extract_section_summaries(
        ordered_keys: list[str],
        hydrated_sections: dict[str, str],
        max_chars_per_section: int = 300,
    ) -> str:
        """Extract title + first paragraph from each section for LLM summary pass.

        Each section's content is truncated to *max_chars_per_section* characters.
        Returns a string with one entry per section: ``### {key}\\n{text}\\n\\n``.
        """
        from graph_kb_api.flows.v3.utils.section_summaries import extract_section_summaries

        return extract_section_summaries(ordered_keys, hydrated_sections, max_chars_per_section)

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        """Strip YAML frontmatter blocks from deliverable content.

        Deliverables from the orchestrate phase often contain metadata
        blocks like:
            ---
            task_id: ...
            status: reviewed
            ---
        These confuse the LLM assembly agent. This method removes them
        while preserving the actual document content.
        """
        # Match YAML frontmatter at the start of content or after a heading
        stripped = re.sub(
            r"^---\s*\n(?:[\w_]+:.*\n)*---\s*\n",
            "",
            content,
            flags=re.MULTILINE,
        )
        # Also strip frontmatter that appears mid-document (after ## heading)
        stripped = re.sub(
            r"\n---\s*\n(?:[\w_]+:.*\n)*---\s*\n",
            "\n",
            stripped,
        )
        return stripped.strip()


class ValidateNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Validates the assembled document for correctness via ValidationAgent (LLM).

    Uses ValidationAgent for comprehensive document validation.
    """

    def __init__(self) -> None:
        super().__init__(node_name="validate")
        self.phase = "assembly"
        self.step_name = "validate"
        self.step_progress = ASSEMBLY_PROGRESS["validate"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget

        generate: GenerateData = state.get("generate", {})

        BudgetGuard.check(budget)

        validation_errors: list[dict[str, Any]] = []
        validation_warnings: list[dict[str, Any]] = []

        await self._emit_progress(ctx, "validate", 0.85, "Validating assembled document...")

        agent = ValidationAgent()

        manifest: DocumentManifest | None = state.get("document_manifest")

        # Build document for validation
        document_sections = generate.get("sections", {})
        assembled_doc = generate.get("assembled_document", "")

        # Hydrate from manifest if available
        if manifest and manifest.get("entries") and ctx.artifact_service:
            document_sections = {}
            assembled_parts = []
            for entry in manifest["entries"]:
                if entry.get("status") in ("final", "reviewed") and entry.get("artifact_ref"):
                    try:
                        content = await ctx.artifact_service.retrieve(entry["artifact_ref"])
                        if content:
                            document_sections[entry.get("spec_section", entry["task_id"])] = content
                            assembled_parts.append(f"## {entry.get('spec_section')}\n\n{content}")
                    except Exception as e:
                        logger.warning(f"ValidateNode: failed to load {entry['task_id']}: {e}")
            assembled_doc = "\n\n".join(assembled_parts)

        document = {
            "title": generate.get("spec_document_path", "Specification"),
            "sections": document_sections,
            "assembled_document": assembled_doc,
        }

        agent_task: AgentTask = {
            "description": "Validate assembled specification document",
            "task_id": f"validation_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "context": {
                "document": document,
                "requirements": self._extract_requirements(state),
            },
        }

        tools = []
        if ctx.workflow_context and ctx.workflow_context.app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools
            tools = get_all_tools(ctx.workflow_context.app_context.get_retrieval_settings())

        result: AgentResult = await agent.execute(
            task=agent_task,
            state=cast("UnifiedSpecState", {"available_tools": tools}),
            workflow_context=ctx.workflow_context,
        )

        # Extract validation results
        is_valid = result.get("is_valid", True)
        quality_score = result.get("quality_score", 0.5)
        completeness_score = result.get("completeness_score", 0.5)

        for issue in result.get("issues", []):
            severity = issue.get("severity", "info")
            if severity == "error":
                validation_errors.append(issue)
            else:
                validation_warnings.append(issue)

        llm_calls = 1

        logger.info(
            f"ValidateNode: LLM validation complete - valid={is_valid}, "
            f"quality={quality_score:.2f}, completeness={completeness_score:.2f}"
        )

        new_budget: BudgetState = self._decrement_budget(budget, str(result))

        # Store validation report via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        report = {
            "is_valid": is_valid,
            "errors": validation_errors,
            "warnings": validation_warnings,
            "sections_count": len(generate.get("sections", {})),
            "spec_path": generate.get("spec_document_path", ""),
        }
        if ctx.artifact_service:
            try:
                ref = await ctx.artifact_service.store(
                    "assembly",
                    "validation_report.json",
                    json.dumps(report, indent=2),
                    f"Validation report: {'passed' if is_valid else 'failed'} ({len(validation_errors)} errors)",
                )
                artifacts_output["assembly.validation_report"] = ref
            except Exception:
                pass  # best-effort

        return NodeExecutionResult.success(
            output={
                "completeness": {
                    **state.get("completeness", {}),
                    "validation": {
                        "is_valid": is_valid,
                        "errors": validation_errors,
                        "warnings": validation_warnings,
                    },
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )

    @staticmethod
    def _extract_requirements(state: AssemblySubgraphState) -> list[dict[str, str]]:
        """Extract validation requirements from context and task DAG.

        Builds a list of requirement checkpoints derived from the spec name,
        user explanation, constraints, and task descriptions so the
        ValidationAgent can verify spec compliance — not just structural quality.
        """
        context: ContextData = state.get("context", {})
        planning: PlanData = state.get("plan", {})
        requirements: list[dict[str, str]] = []

        manifest: DocumentManifest | None = state.get("document_manifest", {})
        spec_name = context.get("spec_name") or manifest.get("spec_name", "")
        if spec_name:
            requirements.append({"type": "spec_name", "description": spec_name})

        user_explanation = context.get("user_explanation", "")
        if user_explanation:
            requirements.append(
                {
                    "type": "user_intent",
                    "description": user_explanation,
                }
            )

        constraints = context.get("constraints", "")
        if constraints:
            requirements.append({"type": "constraints", "description": str(constraints)})

        task_dag = planning.get("task_dag", {})
        for task in task_dag.get("tasks", [])[:20]:
            name = task.get("name", "")
            description = task.get("description", "")
            if name:
                requirements.append(
                    {
                        "type": "task_coverage",
                        "description": f"{name}: {description}",
                    }
                )

        return requirements


class AssemblyApprovalNode(BaseApprovalNode[AssemblySubgraphState]):
    """Approval gate for assembly phase completion.

    Presents the final spec document to user for approval.
    Extends BaseApprovalNode with assembly-specific hooks.
    """

    phase_data_key = "completeness"

    def __init__(self) -> None:
        super().__init__(node_name="assembly_approval")
        self.phase = "assembly"
        self.step_name = "approval"
        self.step_progress = ASSEMBLY_PROGRESS["approval"]

    def _build_summary(self, state: AssemblySubgraphState) -> dict[str, Any]:
        context: ContextData = state.get("context", {})
        completeness: CompletenessData = state.get("completeness", {})
        generate: GenerateData = state.get("generate", {})

        spec_name: str = context.get("spec_name", "Unknown")
        validation = completeness.get("validation", {})
        spec_path: str = generate.get("spec_document_path", "")
        manifest: DocumentManifest | None = state.get("document_manifest")

        sections_generated = len(generate.get("sections", {}))
        if manifest:
            sections_generated = len(
                [e for e in manifest.get("entries", []) if e.get("status") in ("final", "reviewed")]
            )

        # Build manifest entries for download links
        manifest_entries: list[dict[str, Any]] = []
        if manifest:
            for entry in manifest.get("entries", []):
                ref: ArtifactRef | None = entry.get("artifact_ref")
                manifest_entries.append({
                    "task_id": entry.get("task_id", ""),
                    "spec_section": entry.get("spec_section", ""),
                    "status": entry.get("status", "draft"),
                    "token_count": entry.get("token_count", 0),
                    "download_url": ref.get("key", "") if ref else "",
                    "error_message": entry.get("error_message"),
                })

        summary: Dict[str, Any] = {
            "spec_name": spec_name,
            "spec_document_path": spec_path,
            "is_valid": validation.get("is_valid", False),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "errors_count": len(validation.get("errors", [])),
            "warnings_count": len(validation.get("warnings", [])),
            "sections_generated": sections_generated,
        }
        if manifest_entries:
            summary["manifest_entries"] = manifest_entries

        # NOTE: document_preview is added asynchronously in _build_summary_async
        # and merged into the summary by the overridden _execute_step.
        return summary

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        """Override to inject async document_preview into summary before interrupt."""
        # We need to hydrate the document preview before the base class builds the payload.
        # The base class calls _build_summary synchronously, so we handle the async part here.
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        generate: GenerateData = state.get("generate", {})
        manifest: DocumentManifest | None = state.get("document_manifest")

        # Hydrate document preview
        document_preview = await self._hydrate_document_preview(
            manifest, generate, artifact_svc, state.get("artifacts", {})
        )
        # Store preview temporarily so _build_summary can be called by base class
        self._document_preview = document_preview

        # Now delegate to the base class workflow
        result = await super()._execute_step(state, config)
        return result

    def _build_payload_extras(self, state: AssemblySubgraphState, summary: dict[str, Any]) -> dict[str, Any]:
        # Inject the async document_preview into the summary
        preview = getattr(self, "_document_preview", "")
        if preview:
            summary["document_preview"] = preview
        return {}

    def _get_approval_options(self) -> list[InterruptOption]:
        return [
            {"id": "approve", "label": "Approve & Finalize"},
            {"id": "revise", "label": "Request Revisions"},
            {"id": "reject", "label": "Reject"},
        ]

    def _get_approval_message(self, summary: dict[str, Any]) -> str:
        return (
            f"Specification '{summary.get('spec_name', 'Unknown')}' is ready for review. "
            f"{summary['sections_generated']} sections generated. "
            f"Review the document below, then approve to finalize."
        )

    def _process_approve(self, state: AssemblySubgraphState, feedback: str) -> dict[str, Any]:
        completeness: CompletenessData = state.get("completeness", {})
        return {
            "completeness": {
                **completeness,
                "approved": True,
                "approval_decision": "approve",
                "approval_feedback": feedback,
            },
        }

    def _process_revise(self, state: AssemblySubgraphState, feedback: str) -> dict[str, Any]:
        completeness: CompletenessData = state.get("completeness", {})
        output: Dict[str, Any] = {
            "completeness": {
                **completeness,
                "approved": False,
                "approval_decision": "revise",
                "approval_feedback": feedback,
                "needs_revision": True,
            },
        }
        # Reset manifest entry statuses so GenerateNode and AssembleNode
        # re-process them on the revise loop instead of skipping.
        manifest: DocumentManifest | None = state.get("document_manifest")
        if manifest and manifest.get("entries"):
            reset_entries = [
                {**e, "status": "reviewed", "composed_at": None}
                if e.get("status") == "final"
                else e
                for e in manifest["entries"]
            ]
            output["document_manifest"] = {**manifest, "entries": reset_entries}
        # Clear the assembled spec artifact ref so AssembleNode re-runs LLM assembly
        existing_artifacts: Dict[str, ArtifactRef] = dict(state.get("artifacts", {}))
        existing_artifacts.pop("output.spec", None)
        output["artifacts"] = existing_artifacts
        return output

    def _process_reject(self, state: AssemblySubgraphState, feedback: str) -> dict[str, Any]:
        completeness: CompletenessData = state.get("completeness", {})
        context: ContextData = state.get("context", {})
        spec_name: str = context.get("spec_name", "Unknown")
        return {
            "completeness": {
                **completeness,
                "approved": False,
                "approval_decision": "reject",
                "approval_feedback": feedback,
                "rejected": True,
            },
            "workflow_status": "rejected",
            "error": WorkflowError(
                message=f"Specification '{spec_name}' was rejected by user.",
                code="REJECTED",
                phase="assembly",
            ),
        }

    @staticmethod
    async def _hydrate_document_preview(
        manifest: DocumentManifest | None,
        generate: GenerateData,
        artifact_svc: ArtifactService | None,
        artifacts: Dict[str, ArtifactRef] | None = None,
    ) -> str:
        """Build a markdown preview of the assembled document for user review.

        Multi-doc path: hydrates each manifest entry from blob storage and
        concatenates them under section headings.
        Legacy path: loads the final assembled document from the output.spec
        artifact (produced by AssembleNode), NOT the raw pre-assembly sections.

        The preview is token-capped to avoid oversized interrupt payloads.
        """
        max_preview_tokens = 40_000
        estimator = get_token_estimator()

        # Primary: load the LLM-assembled document from output.spec (both paths store it)
        if artifact_svc and artifacts:
            spec_ref: ArtifactRef | None = artifacts.get("output.spec")
            if spec_ref:
                try:
                    assembled = await artifact_svc.retrieve(spec_ref)
                    if assembled:
                        # Unwrap JSON wrapper if the stored content is a JSON envelope
                        assembled = _unwrap_json_document(assembled)
                        if estimator.count_tokens(assembled) > max_preview_tokens:
                            assembled = truncate_to_tokens(assembled, max_preview_tokens)
                            assembled += "\n\n*[Document truncated for preview]*"
                        return assembled
                except Exception as e:
                    logger.warning("AssemblyApprovalNode: failed to load output.spec: %s", e)

        # Fallback: raw sections (should rarely be reached)
        sections = generate.get("sections", {})
        if sections:
            parts = []
            for name, content in sections.items():
                parts.append(f"## {name}\n\n{content}")
            combined = "\n\n".join(parts)
            if estimator.count_tokens(combined) > max_preview_tokens:
                combined = truncate_to_tokens(combined, max_preview_tokens)
                combined += "\n\n*[Document truncated for preview]*"
            return combined

        return ""


# ── Finalize Node ─────────────────────────────────────────────────────


class FinalizeNode(SubgraphAwareNode[AssemblySubgraphState]):
    """Final node that emits 'plan.complete' on workflow completion.

    Wired as the last node in PlanEngine after the assembly subgraph.
    Extracts 'spec_document_url' and 'story_cards_url' from the
    generate phase output and delegates to :func:`emit_complete`.

    Requirement 21.4.
    """

    def __init__(self) -> None:
        super().__init__(node_name="finalize")
        self.phase = "assembly"
        self.step_name = "finalize"
        self.step_progress = ASSEMBLY_PROGRESS["finalize"]

    async def _execute_step(self, state: AssemblySubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        generate_state: GenerateData = state.get("generate", {})
        spec_document_url: str = generate_state.get("spec_document_path", "")

        # Build document manifest payload (Step 19)
        manifest = state.get("document_manifest")

        # Flush transition_log to audit/transitions.jsonl blob (GAP 16)
        transition_log: list[TransitionEntry] = state.get("transition_log", [])
        if ctx.artifact_service and transition_log:
            try:
                jsonl_content: str = "\n".join(json.dumps(entry, default=str) for entry in transition_log)
                await ctx.artifact_service.store(
                    "audit",
                    "transitions.jsonl",
                    jsonl_content,
                    f"Transition log with {len(transition_log)} entries",
                )
            except Exception:
                pass  # Best-effort flush — don't block completion

        has_document_output = bool(
            spec_document_url
            or (
                manifest
                and (
                    manifest.get("entries")
                    or manifest.get("composed_index_ref")
                )
            )
        )

        if has_document_output:
            # Extract composed index URL for backward compat
            composed_index_url = spec_document_url
            if manifest and manifest.get("composed_index_ref"):
                composed_index_url = manifest["composed_index_ref"].get("key", spec_document_url)

            await emit_complete(
                session_id=ctx.session_id,
                document_manifest=manifest,
                spec_document_url=composed_index_url,
                client_id=ctx.client_id,
            )
        else:
            # No document was generated - emit error instead
            try:
                await emit_error(
                    session_id=ctx.session_id,
                    message=(
                        "Plan workflow completed but no document was generated."
                        " The assembly phase may have failed silently."
                    ),
                    code="NO_DOCUMENT",
                    phase="assembly",
                    client_id=ctx.client_id,
                )
            except Exception:
                pass

        return NodeExecutionResult.success(
            output={
                # Defensive fallback: assembly completion also set by AssemblyApprovalNode
                "completed_phases": {"assembly": True},
                "workflow_status": ("completed" if has_document_output else "error"),
            }
        )
