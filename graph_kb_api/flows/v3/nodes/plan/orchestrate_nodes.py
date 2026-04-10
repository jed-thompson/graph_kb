"""Orchestrate subgraph nodes for the /plan command.

Nodes: PruneAfterResearchNode, PruneAfterOrchestrateNode, BudgetCheckNode,
TaskSelectorNode, FetchContextNode, TaskResearchNode, ToolPlanNode,
DispatchNode, WorkerNode, CritiqueNode, ProgressNode.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, Optional, cast

from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.core.llm import LLMService
from graph_kb_api.database.base import get_db_session_ctx
from graph_kb_api.database.document_repositories import DocumentRepository
from graph_kb_api.flows.v3.agents import AgentResult
from graph_kb_api.flows.v3.agents.architect_agent import ArchitectAgent
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import AgentTask, CritiqueResult, ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import ContextData, PlanData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import BudgetState, OrchestrateSubgraphState, PlanState
from graph_kb_api.flows.v3.state.workflow_state import OrchestrateData
from graph_kb_api.flows.v3.tools import get_all_tools
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator
from graph_kb_api.storage.blob_storage import BlobStorage
from graph_kb_api.websocket.plan_events import (
    emit_circuit_breaker,
    emit_manifest_update,
    emit_phase_progress,
    emit_task_start,
    emit_tasks_dag,
)

logger = logging.getLogger(__name__)


# ── Prune Nodes ───────────────────────────────────────────────────────


class PruneAfterResearchNode(SubgraphAwareNode[PlanState]):
    """Prune node that clears inline research data between subgraphs.

    Preserves ArtifactRef entries, findings summary, and approval flag
    while clearing web_results, vector_results, graph_results.
    """

    # Keys to remove from research state — large inline data arrays
    PRUNE_KEYS = {"web_results", "vector_results", "graph_results"}

    def __init__(self) -> None:
        super().__init__(node_name="prune_after_research")
        self.phase = "research"
        self.step_name = "prune_after_research"
        self.step_progress = 1.0

    async def _execute_step(self, state: PlanState, config: RunnableConfig) -> NodeExecutionResult:
        research: ResearchData = state.get("research", {})
        pruned_research = {k: v for k, v in research.items() if k not in self.PRUNE_KEYS}
        return NodeExecutionResult.success(output={"research": pruned_research})


class PruneAfterOrchestrateNode(SubgraphAwareNode[PlanState]):
    """Prune node that clears iteration history between subgraphs.

    Preserves final task outputs, ArtifactRef entries, and summary fields
    while clearing critique_history, iteration_count, current_task_context.
    """

    # Keys to remove from orchestrate state — iteration-related data
    PRUNE_KEYS = {"critique_history", "iteration_count", "current_task_context", "current_draft", "agent_context"}

    def __init__(self) -> None:
        super().__init__(node_name="prune_after_orchestrate")
        self.phase = "orchestrate"
        self.step_name = "prune_after_orchestrate"
        self.step_progress = 1.0

    async def _execute_step(self, state: PlanState, config: RunnableConfig) -> NodeExecutionResult:
        orchestrate = state.get("orchestrate", {})
        pruned_orchestrate = {k: v for k, v in orchestrate.items() if k not in self.PRUNE_KEYS}

        # Selective task result invalidation for re-orchestration (Step 16)
        re_execute_ids = set(state.get("re_execute_task_ids", []))
        if re_execute_ids:
            task_results = list(orchestrate.get("task_results", []))
            task_results = [t for t in task_results if t.get("id") not in re_execute_ids]
            pruned_orchestrate["task_results"] = task_results
            pruned_orchestrate["current_task_index"] = 0
            pruned_orchestrate["all_complete"] = False

        output: Dict[str, Any] = {"orchestrate": pruned_orchestrate}
        # Clear re-orchestration flags and increment cycle counter after processing
        if re_execute_ids:
            output["needs_re_orchestrate"] = False
            output["re_execute_task_ids"] = []
            output["re_orchestration_count"] = state.get("re_orchestration_count", 0) + 1

        return NodeExecutionResult.success(output=output)


# ── Orchestrate Subgraph Nodes ────────────────────────────────────────


class BudgetCheckNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Guard node that checks budget before task execution.

    Uses BudgetGuard.check() and state-only access pattern —
    reads only LangGraph state fields, never touches blob storage.

    On BudgetExhaustedError, emits a budget exhaustion progress event
    and transitions to graceful completion preserving all artifacts
    and state (Requirements 28.1, 28.2).
    """

    def __init__(self) -> None:
        super().__init__(node_name="budget_check")
        self.phase = "orchestrate"
        self.step_name = "budget_check"
        self.step_progress = 0.0

    async def _execute_step(self, state: PlanState, config: RunnableConfig) -> NodeExecutionResult:
        budget: BudgetState = state.get("budget", {})

        # Lazily initialize document_manifest if not yet created (Part II, Step 9).
        output: Dict[str, Any] = {}
        if state.get("document_manifest") is None:
            from datetime import UTC, datetime

            from graph_kb_api.flows.v3.state.plan_state import DocumentManifest

            context = state.get("context", {})
            manifest = DocumentManifest(
                session_id=state.get("session_id", ""),
                spec_name=context.get("spec_name", "Untitled"),
                primary_spec_ref=None,
                entries=[],
                composed_index_ref=None,
                total_documents=0,
                total_tokens=0,
                created_at=datetime.now(UTC).isoformat(),
                finalized_at=None,
            )
            output["document_manifest"] = manifest

        # BudgetGuard.check() raises BudgetExhaustedError — caught by
        # SubgraphAwareNode._execute_async() which triggers a HITL interrupt.
        BudgetGuard.check(budget)
        return NodeExecutionResult.success(output=output)


class TaskSelectorNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Selects the next task to execute from the task DAG.

    Implements topological ordering and dependency checking.
    Marks tasks as ready when all dependencies are complete.
    """

    def __init__(self) -> None:
        super().__init__(node_name="task_selector")
        self.phase = "orchestrate"
        self.step_name = "task_selector"
        self.step_progress = 0.0

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        # Lazily initialize document_manifest if not yet created.
        # (Previously done in BudgetCheckNode which has been removed.)
        manifest_init: Dict[str, Any] = {}
        if state.get("document_manifest") is None:
            from datetime import UTC, datetime

            from graph_kb_api.flows.v3.state.plan_state import DocumentManifest

            context = state.get("context", {})
            manifest_init["document_manifest"] = DocumentManifest(
                session_id=state.get("session_id", ""),
                spec_name=context.get("spec_name", "Untitled"),
                primary_spec_ref=None,
                entries=[],
                composed_index_ref=None,
                total_documents=0,
                total_tokens=0,
                created_at=datetime.now(UTC).isoformat(),
                finalized_at=None,
            )

        planning: PlanData = state.get("plan", {})
        orchestrate: OrchestrateData = state.get("orchestrate", {})

        task_dag = planning.get("task_dag", {})
        tasks = task_dag.get("tasks", [])
        edges = task_dag.get("dag_edges", task_dag.get("edges", []))
        task_results = orchestrate.get("task_results", [])

        # Build dependency graph
        dependencies: Dict[str, list] = {t.get("id"): [] for t in tasks}
        for src, dst in edges:
            if dst in dependencies:
                dependencies[dst].append(src)

        # Track completed and failed tasks — both should be excluded from
        # the ready queue to prevent infinite retry of tasks that errored.
        finished_ids = {t.get("id") for t in task_results if t.get("status") in ("done", "failed", "error")}

        # Find ready tasks (all dependencies complete and not already finished)
        ready_tasks = []
        for task in tasks:
            task_id = task.get("id")
            if task_id not in finished_ids:
                task_deps = dependencies.get(task_id, [])
                if all(dep in finished_ids for dep in task_deps):
                    ready_tasks.append(task)

        # Select next task (priority: high -> medium -> low, fallback to first ready)
        next_task = None
        for priority in ["high", "medium", "low"]:
            for task in ready_tasks:
                if task.get("priority", "medium") == priority:
                    next_task = task
                    break
            if next_task:
                break
        # Fallback: pick first ready task if no priority match
        if not next_task and ready_tasks:
            next_task = ready_tasks[0]

        output: Dict[str, Any] = {
            "orchestrate": {
                **orchestrate,
                "ready_tasks": [t.get("id") for t in ready_tasks],
                "current_task": next_task if next_task else {},
                "current_task_index": orchestrate.get("current_task_index", 0),
                "iteration_count": 0,
                "critique_history": [],
            }
        }

        if not next_task and not ready_tasks and len(finished_ids) < len(tasks):
            # Stuck - some tasks have unmet dependencies or all failed.
            # Do NOT set all_complete — report as blocked with stalled task IDs.
            stalled_ids = [t.get("id") for t in tasks if t.get("id") not in finished_ids]
            output["orchestrate"]["blocked"] = True
            output["orchestrate"]["stalled_tasks"] = stalled_ids
            output["orchestrate"]["all_complete"] = False
        elif len(finished_ids) == len(tasks):
            output["orchestrate"]["all_complete"] = True

        # Emit plan.tasks.dag on first invocation and on resume so frontend can render task cards
        dag_emitted = orchestrate.get("dag_emitted", False)
        if not dag_emitted and tasks:
            configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
            session_id = state.get("session_id", "")
            client_id: str | None = configurable.get("client_id")
            try:
                await emit_tasks_dag(
                    session_id=session_id,
                    tasks=[
                        {
                            "task_id": t.get("id", ""),
                            "task_name": t.get("name", ""),
                            "priority": t.get("priority", "medium"),
                            "dependencies": dependencies.get(t.get("id"), []),
                        }
                        for t in tasks
                    ],
                    client_id=client_id,
                )
                output["orchestrate"]["dag_emitted"] = True
            except Exception as e:
                logger.warning(f"TaskSelectorNode emit_tasks_dag failed: {e}")

        return NodeExecutionResult.success(output={**manifest_init, **output})


class FetchContextNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Fetches relevant context for the selected task.

    Hydrates ArtifactRefs from ArtifactService to get full content.
    """

    def __init__(self) -> None:
        super().__init__(node_name="fetch_context")
        self.phase = "orchestrate"
        self.step_name = "fetch_context"
        self.step_progress = 0.15

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        workflow_context: WorkflowContext | None = configurable.get("context")

        orchestrate: OrchestrateData = state.get("orchestrate", {})
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})

        current_task = orchestrate.get("current_task", {})
        if not current_task:
            return NodeExecutionResult.success(
                output={
                    "orchestrate": {**orchestrate, "current_task_context": {}},
                }
            )

        task_id = current_task.get("id")
        task_context: Dict[str, Any] = {
            "task_id": task_id,
            "spec_name": context.get("spec_name"),
            "spec_description": context.get("spec_description"),
            "user_explanation": context.get("user_explanation"),
            "constraints": context.get("constraints"),
        }

        # Add research findings
        findings = research.get("findings", {})
        if findings:
            task_context["research_summary"] = findings.get("summary", "")
            task_context["key_insights"] = findings.get("key_insights", [])

        # Hydrate artifacts if service available (Pattern B — hydrate on demand)
        artifacts = state.get("artifacts", {})
        if artifact_svc and artifacts:
            for key, ref in artifacts.items():
                if key.startswith("research.") or key.startswith("context."):
                    try:
                        content = await artifact_svc.retrieve(ref)
                        if isinstance(content, str):
                            task_context[f"artifact_{key}"] = json.loads(content)
                        else:
                            task_context[f"artifact_{key}"] = content
                    except Exception as e:
                        logger.debug(f"Failed to hydrate artifact {key}: {e}")

        # Scoped supporting document sections (Step 11, Part I: D7)
        relevant_docs = current_task.get("relevant_docs", [])
        doc_index = context.get("document_section_index", [])
        blob_storage = workflow_context.blob_storage if workflow_context else None
        if relevant_docs and doc_index and artifact_svc:
            task_context["supporting_doc_sections"] = await self._load_relevant_doc_sections(
                relevant_docs, doc_index, artifact_svc, blob_storage=blob_storage, max_tokens=4000
            )

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "current_task_context": task_context,
                }
            }
        )

    async def _load_relevant_doc_sections(
        self,
        relevant_docs: list[dict],
        document_section_index: list[dict],
        artifact_svc: ArtifactService,
        blob_storage: BlobStorage | None = None,
        max_tokens: int = 4000,
    ) -> list[dict]:
        """Load section-scoped content from supporting documents for a task.

        Args:
            relevant_docs: [{doc_id, sections: ["Heading A", "Heading B"]}]
            document_section_index: composite index from CollectContextNode
            artifact_svc: for blob retrieval
            blob_storage: shared BlobStorage from WorkflowContext (avoids re-init)
            max_tokens: token budget for combined supporting doc content

        Returns:
            List of {doc_id, filename, sections: [{heading, content}]}
        """
        from graph_kb_api.flows.v3.utils.token_estimation import truncate_to_tokens

        if not relevant_docs or not document_section_index:
            return []

        storage = blob_storage or BlobStorage.from_env()
        index_by_doc = {d["doc_id"]: d for d in document_section_index}
        loaded: list[dict] = []
        tokens_used = 0
        blob_cache: dict[str, str] = {}  # Cache blob content per doc_id

        for ref in relevant_docs:
            if tokens_used >= max_tokens:
                break

            doc_id = ref.get("doc_id", "")
            section_headings = ref.get("sections", [])
            idx_entry = index_by_doc.get(doc_id)
            if not idx_entry:
                continue

            # Load document blob once per doc_id (avoid N+1 DB + blob queries)
            doc_content: str | None = blob_cache.get(doc_id)
            if doc_content is None and doc_id not in blob_cache:
                try:
                    async with get_db_session_ctx() as db_session:
                        doc_repo = DocumentRepository(db_session)
                        doc = await doc_repo.get(doc_id)
                    if doc:
                        artifact = await storage.backend.retrieve(doc.storage_key)
                        if artifact and isinstance(artifact.content, str):
                            blob_cache[doc_id] = artifact.content
                            doc_content = artifact.content
                        else:
                            blob_cache[doc_id] = ""
                except Exception as e:
                    logger.debug(f"Failed to load document {doc_id}: {e}")
                    blob_cache[doc_id] = ""

            if not doc_content:
                continue

            doc_sections: list[dict] = []
            for heading in section_headings:
                if tokens_used >= max_tokens:
                    break
                for sec in idx_entry.get("sections", []):
                    if sec["heading"] == heading:
                        section_content = doc_content[sec["start_char"] : sec["end_char"]]
                        truncated = truncate_to_tokens(section_content, max_tokens - tokens_used)
                        doc_sections.append({"heading": heading, "content": truncated})
                        tokens_used += get_token_estimator().count_tokens(truncated)
                        break

            if doc_sections:
                loaded.append(
                    {
                        "doc_id": doc_id,
                        "filename": idx_entry.get("filename", "unknown"),
                        "sections": doc_sections,
                    }
                )

        return loaded


class GapNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Identifies gaps in context for the current task via GapAnalysisAgent (LLM).

    Primary: Uses GapAnalysisAgent for semantic context gap detection.
    Fallback: Deterministic heuristic checks when LLM unavailable.
    """

    def __init__(self) -> None:
        super().__init__(node_name="gap")
        self.phase = "orchestrate"
        self.step_name = "gap"
        self.step_progress = 0.25

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        orchestrate: OrchestrateData = state.get("orchestrate", {})
        task_context = orchestrate.get("current_task_context", {})
        current_task = orchestrate.get("current_task", {})
        budget: BudgetState = state.get("budget", {})
        session_id: str = state.get("session_id", "")

        if not current_task:
            return NodeExecutionResult.success(output={"orchestrate": {**orchestrate, "context_gaps": []}})

        BudgetGuard.check(budget)

        gaps: list = []

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")

        if not llm:
            raise RuntimeError("GapNode requires an LLM but none was provided in config.")

        from graph_kb_api.flows.v3.agents.gap_analysis_agent import GapAnalysisAgent

        agent = GapAnalysisAgent()
        workflow_context: WorkflowContext | None = configurable.get("context")

        if not workflow_context:
            return NodeExecutionResult.success(output={"orchestrate": {**orchestrate, "context_gaps": []}})

        # Build tools from workflow context
        app_context = workflow_context.app_context
        if app_context:
            retrieval_config = app_context.get_retrieval_settings()
            tools = get_all_tools(retrieval_config)
        else:
            tools = []

        agent_task: AgentTask = {
            "description": "Task-level gap analysis",
            "task_id": f"task_gap_{session_id}_{uuid.uuid4().hex[:8]}",
            "specification": {
                "spec_name": task_context.get("spec_name", ""),
                "spec_description": task_context.get("spec_description", ""),
                "user_explanation": task_context.get("user_explanation", ""),
            },
            "research_findings": {
                "summary": task_context.get("research_summary", ""),
                "key_insights": task_context.get("key_insights", []),
            },
            "context": {
                "task": {
                    "task_id": current_task.get("id", ""),
                    "task_name": current_task.get("name", ""),
                    "skills_required": current_task.get("skills_required", []),
                },
                "supporting_doc_sections": task_context.get("supporting_doc_sections", []),
            },
        }

        agent_state = {"available_tools": tools}
        result: AgentResult = await agent.execute(
            task=agent_task, state=agent_state, workflow_context=workflow_context,
        )

        # Convert agent gaps to node format
        for gap in result.get("gaps", []):
            gaps.append(
                {
                    "type": gap.get("category", "context"),
                    "description": gap.get("description", ""),
                    "severity": gap.get("impact", "medium"),
                    "question": gap.get("question_to_ask", ""),
                    "suggested_resolution": gap.get("suggested_resolution", ""),
                    "source": "llm_semantic",
                }
            )

        llm_calls = 1
        tokens_used: int = get_token_estimator().count_tokens(str(result))

        logger.info(f"GapNode: LLM semantic analysis found {len(gaps)} gaps for task {current_task.get('id')}")

        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "context_gaps": gaps,
                },
                "budget": new_budget,
            }
        )


class TaskContextInputNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Optional HITL node for collecting user context when task context is sparse.

    Conditionally interrupts the workflow to ask the user for additional
    context (URLs, documents) when the current task lacks sufficient
    supporting material. Passes through silently when context is adequate.

    Routing: fetch_context → task_context_input → task_research → ...existing flow...
    """

    def __init__(self) -> None:
        super().__init__(node_name="task_context_input")
        self.phase = "orchestrate"
        self.step_name = "task_context_input"
        self.step_progress = 0.25

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        orchestrate: OrchestrateData = state.get("orchestrate", {})
        current_task = orchestrate.get("current_task", {})

        if not current_task:
            return NodeExecutionResult.success(output={})

        # Determine if context is sparse enough to warrant user input
        relevant_docs = current_task.get("relevant_docs", [])
        task_context = orchestrate.get("current_task_context", {})
        has_artifact_context = any(k.startswith("artifact_context.") for k in task_context if isinstance(k, str))
        has_research = bool(task_context.get("research_summary"))

        # Skip interrupt if context is sufficient (GapNode no longer runs, so
        # sparse-context detection is based on artifact/research/doc presence alone)
        if has_artifact_context or has_research or len(relevant_docs) > 0:
            return NodeExecutionResult.success(output={})

        # Emit interrupt for user input (Step 12)
        task_name = current_task.get("name", "Unknown Task")
        spec_section = current_task.get("spec_section", "")

        interrupt_payload: Dict[str, Any] = {
            "type": "task_context_input",
            "task_name": task_name,
            "spec_section": spec_section,
            "context_gaps": [
                "No artifact context available",
                "No supporting documents mapped to this task",
            ]
            if not task_context.get("artifact_context")
            else [],
            # Snapshot completed task_results so handle_reconnect can restore
            # task statuses after page refresh (parent checkpoint lacks
            # orchestrate subgraph state when use_default_checkpointer=False).
            "task_results": list(orchestrate.get("task_results") or []),
        }

        # Use interrupt() to pause workflow and wait for user response
        user_response = interrupt(interrupt_payload)

        # Merge user-provided context into current_task_context
        output: Dict[str, Any] = {}
        if user_response and isinstance(user_response, dict):
            updated_context = {**task_context}
            context_urls = user_response.get("context_urls", "")
            context_note = user_response.get("context_note", "")

            if context_urls:
                updated_context["user_provided_urls"] = context_urls
            if context_note:
                updated_context["user_context_note"] = context_note

            output["orchestrate"] = {**orchestrate, "current_task_context": updated_context}

        return NodeExecutionResult.success(output=output)


class TaskResearchNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Performs focused per-task research before worker execution.

    Uses ResearchAgent to investigate task-specific questions based on the
    spec section type and task context_requirements.

    Stores results via ArtifactService and merges into current_task_context.
    Skips research when task doesn't require research context.
    """

    def __init__(self) -> None:
        super().__init__(node_name="task_research")
        self.phase = "orchestrate"
        self.step_name = "task_research"
        self.step_progress = 0.30

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        budget: BudgetState = state.get("budget", {})
        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")

        orchestrate: OrchestrateData = state.get("orchestrate", {})
        research: ResearchData = state.get("research", {})
        current_task = orchestrate.get("current_task", {})
        context_gaps = orchestrate.get("context_gaps", [])
        task_context = orchestrate.get("current_task_context", {})

        if not current_task:
            return NodeExecutionResult.success(output={"orchestrate": orchestrate})

        task_id = current_task.get("id", "unknown")
        context_requirements = current_task.get("context_requirements", [])

        # Run research when task explicitly requires research findings.
        # (context_gaps is always empty after GapNode was removed from the graph;
        # research eligibility is now determined solely by context_requirements.)
        needs_research: bool = "research_findings" in context_requirements
        if not needs_research:
            logger.info(
                "TaskResearchNode: skipping research for task %s (no research_findings in context_requirements)",
                task_id,
            )
            return NodeExecutionResult.success(output={"orchestrate": orchestrate})

        BudgetGuard.check(budget)

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="orchestrate",
                step="task_research",
                message=f"Researching context for '{current_task.get('name', task_id)}'",
                progress_pct=0.30,
                client_id=client_id,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning(f"TaskResearchNode emit_phase_progress failed: {e}")

        task_research_results: Dict[str, Any] = {}
        llm_calls = 0
        tokens_used = 0

        try:
            from graph_kb_api.flows.v3.agents.research_agent import ResearchAgent

            workflow_context = configurable.get("context")
            if not workflow_context:
                raise RuntimeError("TaskResearchNode requires workflow_context")

            # Build tools from workflow context
            app_context = workflow_context.app_context
            if app_context:
                retrieval_config = app_context.get_retrieval_settings()
                tools = get_all_tools(retrieval_config)
            else:
                tools = []

            agent = ResearchAgent(client_id=client_id)

            spec_section = current_task.get("spec_section", "general")
            task_description = current_task.get("description", "")
            gap_descriptions = [g.get("description", "") for g in context_gaps]

            # Build focused research task with full spec context
            context_data: ContextData = state.get("context", {})

            # Scope document contents to docs relevant to this task.
            # Falls back to all docs when relevant_docs is empty (e.g. no
            # primary spec uploaded or DecomposeAgent returned empty refs).
            _relevant_docs = current_task.get("relevant_docs", [])
            _all_docs = context_data.get("uploaded_document_contents", [])
            _relevant_doc_ids = {rd.get("doc_id") for rd in _relevant_docs if rd.get("doc_id")}
            scoped_doc_contents = (
                [d for d in _all_docs if d.get("doc_id") in _relevant_doc_ids] if _relevant_doc_ids else _all_docs
            )
            agent_task: AgentTask = {
                "description": (
                    f"Focused research for the '{spec_section}' spec section. "
                    f"Task: {task_description}. "
                    f"Known gaps: {'; '.join(gap_descriptions[:5]) if gap_descriptions else 'None'}."
                ),
                "task_id": f"task_research_{task_id}_{uuid.uuid4().hex[:8]}",
                "context": {
                    "spec_section": spec_section,
                    "task_name": current_task.get("name", ""),
                    "task_description": task_description,
                    "context_gaps": context_gaps[:5],
                    "existing_research_summary": research.get("findings", {}).get("summary", ""),
                    "existing_key_insights": research.get("findings", {}).get("key_insights", []),
                    "spec_name": context_data.get("spec_name", ""),
                    "user_explanation": context_data.get("user_explanation", ""),
                    "constraints": context_data.get("constraints", {}),
                    "uploaded_document_contents": scoped_doc_contents,
                    "document_section_index": context_data.get("document_section_index", []),
                    "target_repo_id": context_data.get("target_repo_id", ""),
                    "supporting_docs": context_data.get("supporting_docs", []),
                },
            }

            agent_state = {"available_tools": tools, "session_id": session_id}
            result: AgentResult = await agent.execute(
                task=agent_task, state=agent_state, workflow_context=workflow_context,
            )

            # ResearchAgent.execute() returns {"output": json_string, ...}
            # Parse the serialized findings from the "output" key
            agent_findings: Dict[str, Any] = {}
            raw_output = result.get("output")
            if isinstance(raw_output, str):
                try:
                    agent_findings = json.loads(raw_output)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(raw_output, dict):
                agent_findings = raw_output
            if not agent_findings:
                agent_findings = result.get("research_findings", {})

            task_research_results = {
                "task_id": task_id,
                "findings": agent_findings,
                "summary": agent_findings.get("summary", ""),
            }
            llm_calls = result.get("llm_calls_used", 1)

            tokens_used = get_token_estimator().count_tokens(str(task_research_results))

            logger.info(f"TaskResearchNode: completed research for task {task_id}")
        except Exception as e:
            logger.warning(f"TaskResearchNode: research failed for task {task_id}: {e}")
            task_research_results = {"task_id": task_id, "error": str(e)}

        # Store via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        if artifact_svc and task_research_results:
            try:
                ref = await artifact_svc.store(
                    "orchestrate",
                    f"tasks/{task_id}/research.json",
                    json.dumps(task_research_results, indent=2, default=str),
                    f"Task-specific research for: {current_task.get('name', task_id)}",
                )
                artifacts_output[f"orchestrate.{task_id}.research"] = ref
            except Exception as e:
                logger.warning(f"TaskResearchNode: artifact store failed: {e}")

        new_budget = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

        # Emit research summary for frontend TaskContextPanel (Step 11c)
        if task_research_results and task_research_results.get("summary"):
            research_summary = task_research_results["summary"]
            key_insights = task_research_results.get("findings", {}).get("key_insights", [])
            if key_insights:
                bullets = "\n".join(f"• {ins}" for ins in key_insights[:5])
                research_summary = f"{research_summary}\n\n**Key findings:**\n{bullets}"
            try:
                await emit_phase_progress(
                    session_id=session_id,
                    phase="orchestrate",
                    step="task_research",
                    message=f"Research complete for '{current_task.get('name', task_id)}'",
                    progress_pct=0.50,
                    client_id=client_id,
                    task_id=task_id,
                    agent_content=research_summary,
                )
            except Exception as e:
                logger.warning(f"TaskResearchNode research summary emit failed: {e}")

        # Merge task research into current_task_context
        updated_task_context = {
            **task_context,
            "task_research": task_research_results,
        }

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "current_task_context": updated_task_context,
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )


class ToolPlanNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Plans which tools to use for the current task.

    Maps task requirements to available tools.

    Requirements: 22.5
    """

    def __init__(self) -> None:
        super().__init__(node_name="tool_plan")
        self.phase = "orchestrate"
        self.step_name = "tool_plan"
        self.step_progress = 0.35

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        orchestrate = state.get("orchestrate", {})
        planning = state.get("plan", {})

        current_task = orchestrate.get("current_task", {})
        if not current_task:
            return NodeExecutionResult.success(
                output={
                    "orchestrate": {**orchestrate, "tool_assignments": {}},
                }
            )

        task_id = current_task.get("id")
        assignments = planning.get("assignments", [])

        # Find assignment for this task
        task_assignment = None
        for assignment in assignments:
            if assignment.get("task_id") == task_id:
                task_assignment = assignment
                break

        if not task_assignment:
            # Default assignment
            task_assignment = {
                "task_id": task_id,
                "agent_type": current_task.get("agent_type", "general"),
                "tools": ["llm"],
            }

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "tool_assignments": task_assignment,
                }
            }
        )


class DispatchNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Dispatches the task to the appropriate worker agent.

    Prepares the dispatch configuration for WorkerNode.
    """

    def __init__(self) -> None:
        super().__init__(node_name="dispatch")
        self.phase = "orchestrate"
        self.step_name = "dispatch"
        self.step_progress = 0.45
        self._blob_cache: dict[str, str] = {}  # Cache blob content per doc_id

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        workflow_context: WorkflowContext | None = configurable.get("context")
        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")

        orchestrate: OrchestrateData = state.get("orchestrate", {})

        current_task = orchestrate.get("current_task", {})
        tool_assignments = orchestrate.get("tool_assignments", {})
        task_context = orchestrate.get("current_task_context", {})

        if not current_task:
            return NodeExecutionResult.success(
                output={
                    "orchestrate": {**orchestrate, "agent_context": {}, "assigned_agent": ""},
                }
            )

        task_id = current_task.get("id", "unknown")
        task_name = current_task.get("name", "Unknown")
        agent_type = tool_assignments.get("agent_type", current_task.get("agent_type", "general"))

        # Build agent_context by combining task context + tool assignments
        # Note: artifacts already hydrated by FetchContextNode into task_context
        agent_context: Dict[str, Any] = {
            "task_id": task_id,
            "task_name": task_name,
            "task_description": current_task.get("description", ""),
            "agent_type": agent_type,
            "section_type": current_task.get("section_type", ""),
            "spec_section": current_task.get("spec_section", ""),
            "context_requirements": current_task.get("context_requirements", []),
            "tools": tool_assignments.get("tools", ["llm"]),
            "context": task_context,
        }

        # Emit plan.task.start event with spec section context (Step 11b)
        try:
            spec_section: str = current_task.get("spec_section", "")
            spec_section_content: str | None = None

            # Load truncated spec section content for frontend panel
            if spec_section and artifact_svc:
                context = state.get("context", {})
                doc_index = context.get("document_section_index", [])
                primary_entries = [d for d in doc_index if d.get("role") == "primary"]
                if primary_entries:
                    # Load primary document blob once per doc_id (cached across task dispatches)
                    primary_id = context.get("primary_document_id", "")
                    primary_blob: str | None = None
                    if primary_id and primary_id not in self._blob_cache:
                        try:
                            storage = workflow_context.blob_storage if workflow_context else BlobStorage.from_env()
                            async with get_db_session_ctx() as db_session:
                                doc_repo = DocumentRepository(db_session)
                                doc = await doc_repo.get(primary_id)
                            if doc:
                                artifact = await storage.backend.retrieve(doc.storage_key)
                                if artifact and isinstance(artifact.content, str):
                                    self._blob_cache[primary_id] = artifact.content
                                else:
                                    self._blob_cache[primary_id] = ""
                        except Exception as exc:
                            logger.debug(f"DispatchNode: failed to load primary doc: {exc}")
                            self._blob_cache[primary_id] = ""
                    primary_blob = self._blob_cache.get(primary_id)

                    for sec in primary_entries[0].get("sections", []):
                        if sec["heading"] == spec_section and primary_blob:
                            section_text = primary_blob[sec["start_char"] : sec["end_char"]]
                            from graph_kb_api.flows.v3.utils.token_estimation import (
                                truncate_to_tokens,
                            )

                            spec_section_content = truncate_to_tokens(section_text, 3000)
                            break

            if spec_section_content:
                agent_context["spec_section_content"] = spec_section_content

            await emit_task_start(
                session_id=session_id,
                task_id=task_id,
                task_name=task_name,
                client_id=client_id,
                spec_section=spec_section or None,
                spec_section_content=spec_section_content,
            )
        except Exception as e:
            logger.warning(f"DispatchNode emit_task_start failed: {e}")

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "agent_context": agent_context,
                    "assigned_agent": agent_type,
                }
            }
        )


class WorkerNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Executes the task using the assigned agent.

    Dispatches to the correct agent (ArchitectAgent, ResearchAgent,
    LeadEngineerAgent, CodeGeneratorAgent) based on the ``agent_type``
    field in orchestrate state.  Uses _AgentAppContext adapter for all
    agent calls.

    Stores drafts via ArtifactService.store() at path
    orchestrate/tasks/{task_id}/.

    Requirements: 23.1, 23.2, 23.3
    """

    # Map agent_type strings to agent classes
    _AGENT_REGISTRY: Dict[str, str] = {
        "architect": "graph_kb_api.flows.v3.agents.architect_agent.ArchitectAgent",
        "research": "graph_kb_api.flows.v3.agents.research_agent.ResearchAgent",
        "lead_engineer": "graph_kb_api.flows.v3.agents.lead_engineer_agent.LeadEngineerAgent",
        "code_generator": "graph_kb_api.flows.v3.agents.code_generator.CodeGeneratorAgent",
        "code_analyst": "graph_kb_api.flows.v3.agents.code_analyst.CodeAnalystAgent",
        "doc_extractor": "graph_kb_api.flows.v3.agents.doc_extractor_agent.DocExtractorAgent",
        "backend": "graph_kb_api.flows.v3.agents.architect_agent.ArchitectAgent",
        "frontend": "graph_kb_api.flows.v3.agents.lead_engineer_agent.LeadEngineerAgent",
        "fullstack": "graph_kb_api.flows.v3.agents.architect_agent.ArchitectAgent",
        "general": "graph_kb_api.flows.v3.agents.architect_agent.ArchitectAgent",
    }

    def __init__(self) -> None:
        super().__init__(node_name="worker")
        self.phase = "orchestrate"
        self.step_name = "worker"
        self.step_progress = 0.60

    def _resolve_agent(self, agent_type: str) -> Any:
        """Dynamically import and instantiate the agent for the given type."""
        import importlib

        dotted = self._AGENT_REGISTRY.get(agent_type, self._AGENT_REGISTRY["general"])
        module_path, class_name = dotted.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls()

    @staticmethod
    def _extract_string_content(raw_output: Any, full_result: Dict[str, Any]) -> str:
        """Extract a markdown string from agent output.

        Agents may return a plain string, or a dict with the real content
        nested under varying keys.  This method walks the value looking for
        the longest string — which is almost always the drafted document.
        Falls back to JSON serialization only when no string is found.
        """
        if isinstance(raw_output, str) and raw_output:
            return raw_output

        if isinstance(raw_output, dict):
            # Try well-known keys first
            for key in ("assembled_document", "draft", "content", "summary", "document", "text", "output"):
                val = raw_output.get(key)
                if isinstance(val, str) and len(val) > 50:
                    return val
            # Fallback: pick the longest string value in the dict
            best = ""
            for val in raw_output.values():
                if isinstance(val, str) and len(val) > len(best):
                    best = val
            if best:
                return best

        return json.dumps(full_result, indent=2, default=str)

    @staticmethod
    def _build_prior_sections_summary(
        task_results: list[Dict[str, Any]],
        max_tokens: int = 1500,
    ) -> str:
        """Build compressed bullet summary of completed sections.

        Delegates to the standalone utility for easier testing.
        """
        from graph_kb_api.flows.v3.utils.prior_sections_summary import build_prior_sections_summary

        return build_prior_sections_summary(task_results, max_tokens)

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        budget: BudgetState = state.get("budget", {})

        orchestrate: OrchestrateData = state.get("orchestrate", {})
        agent_context = orchestrate.get("agent_context", {})

        if not agent_context:
            return NodeExecutionResult.success(
                output={
                    "orchestrate": {
                        **orchestrate,
                        "current_draft": "",
                        "task_results": orchestrate.get("task_results", []),
                    },
                }
            )

        BudgetGuard.check(budget)

        session_id = state.get("session_id", "")
        client_id = configurable.get("client_id")

        task_id = agent_context.get("task_id", "unknown")
        task_name = agent_context.get("task_name", "Unknown Task")
        task_description = agent_context.get("task_description", "")
        task_context = agent_context.get("context", {})
        agent_type = agent_context.get("agent_type", "general")

        # Build the agent app_context adapter
        workflow_context = configurable.get("context")

        if not workflow_context:
            raise RuntimeError("WorkerNode requires workflow_context")

        # Enrich description for spec-section tasks
        section_type = agent_context.get("section_type", "")
        spec_section = agent_context.get("spec_section", "")

        if section_type == "analysis_and_draft" and spec_section:
            enriched_description = (
                f"Analyze and draft the '{spec_section}' section of the specification. {task_description}"
            )
        else:
            enriched_description = task_description or f"Execute task: {task_name}"

        # Inject prior sections summary into agent_context (Change 2)
        task_results = orchestrate.get("task_results", [])
        prior_summary = self._build_prior_sections_summary(task_results)
        if prior_summary:
            agent_context = {**agent_context, "prior_sections_summary": prior_summary}

        # Build the AgentTask the agent expects
        agent_task: AgentTask = {
            "description": enriched_description,
            "title": task_name,
            "task_id": task_id,
            "context": task_context,
        }

        # Build tools from workflow context
        app_context = workflow_context.app_context
        if app_context:
            retrieval_config = app_context.get_retrieval_settings()
            tools = get_all_tools(retrieval_config)
        else:
            tools = []

        # Build the state dict the agent expects
        agent_state = {
            "agent_context": agent_context,
            "available_tools": tools,
        }

        output_content = ""
        llm_calls = 1
        task_status = "done"

        iteration_count = orchestrate.get("iteration_count", 0)
        if iteration_count > 0:
            # Revision pass: re-emit task start so the UI transitions from
            # 'critiquing' → 'in_progress' instead of staying frozen.
            try:
                await emit_task_start(
                    session_id=session_id,
                    task_id=task_id,
                    task_name=task_name,
                    client_id=client_id,
                    spec_section=agent_context.get("spec_section") or None,
                )
            except Exception as e:
                logger.warning(f"WorkerNode emit_task_start (revision) failed: {e}")

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="orchestrate",
                step="worker",
                message=f"Executing task '{task_name}' via {agent_type} agent",
                progress_pct=0.60,
                client_id=client_id,
                task_id=task_id,
                agent_type=agent_type,
            )
        except Exception as e:
            logger.warning(f"WorkerNode emit_phase_progress failed: {e}")

        try:
            agent = self._resolve_agent(agent_type)
            result = await agent.execute(task=agent_task, state=agent_state, workflow_context=workflow_context)

            # Agents return different keys — normalize to a string draft.
            # Some agents return {"output": {"assembled_document": "...", ...}}
            # so we must unwrap dicts to extract the actual markdown content.
            raw_output = (
                result.get("agent_draft")
                or result.get("output")
                or result.get("research_findings", {}).get("summary", "")
            )
            output_content = self._extract_string_content(raw_output, result)
        except Exception as e:
            logger.warning(f"WorkerNode agent dispatch failed for {task_id} (agent_type={agent_type}): {e}")
            task_status = "failed"
            output_content = f"# {task_name}\n\nAgent dispatch failed ({agent_type}): {e}"

        try:
            # Emit agent_content so the frontend can show what the LLM produced
            # Truncate to ~4K chars to avoid oversized WebSocket frames
            agent_content_preview = output_content[:4000] if output_content else None
            await emit_phase_progress(
                session_id=session_id,
                phase="orchestrate",
                step="worker",
                message=f"Task '{task_name}' execution complete, storing draft",
                progress_pct=0.70,
                client_id=client_id,
                task_id=task_id,
                agent_type=agent_type,
                agent_content=agent_content_preview,
            )
        except Exception as e:
            logger.warning(f"WorkerNode emit_phase_progress failed: {e}")

        # Store draft via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        draft_ref = None
        deliverable_ref = None

        if artifact_svc and output_content:
            draft_ref = await artifact_svc.store(
                "orchestrate",
                f"tasks/{task_id}/draft.md",
                output_content,
                f"Draft for task: {task_name} (agent: {agent_type})",
            )
            artifacts_output[f"orchestrate.{task_id}.draft"] = draft_ref

            # Re-store as deliverable with YAML frontmatter (Step 10).
            slug = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-")[:60]
            tokens_used = get_token_estimator().count_tokens(output_content)
            frontmatter = (
                f"---\ntask_id: {task_id}\n"
                f'spec_section: "{spec_section or "general"}"\n'
                f"status: reviewed\nagent_type: {agent_type}\n"
                f"section_type: {section_type or 'general'}\n"
                f"dependencies: {json.dumps(agent_context.get('dependencies', []))}\n"
                f"token_count: {tokens_used}\n"
                f"composed_at: null\n---\n\n"
            )
            deliverable_content = frontmatter + output_content
            deliverable_ref = await artifact_svc.store(
                "deliverables",
                f"{task_id}/{slug}.md",
                deliverable_content,
                f"Deliverable for task: {task_name}",
            )
            artifacts_output[f"deliverables.{task_id}"] = deliverable_ref

        # Upsert manifest entry (Step 10 — read-modify-write per D4).
        manifest_output: Dict[str, Any] = {}
        manifest = state.get("document_manifest")
        if manifest is None and deliverable_ref is not None:
            from datetime import UTC, datetime

            from graph_kb_api.flows.v3.state.plan_state import DocumentManifest

            manifest = DocumentManifest(
                session_id=state.get("session_id", ""),
                spec_name=state.get("context", {}).get("spec_name", "Untitled"),
                primary_spec_ref=None,
                entries=[],
                composed_index_ref=None,
                total_documents=0,
                total_tokens=0,
                created_at=datetime.now(UTC).isoformat(),
                finalized_at=None,
            )

        if manifest is not None and deliverable_ref is not None:
            from graph_kb_api.flows.v3.state.plan_state import DocumentManifestEntry

            entries = list(manifest["entries"])
            entry_status = "reviewed" if task_status == "done" else ("error" if task_status == "error" else "failed")
            new_entry = DocumentManifestEntry(
                task_id=task_id,
                spec_section=spec_section or "Unknown",
                artifact_ref=deliverable_ref,
                status=entry_status,
                section_type=section_type,
                dependencies=agent_context.get("dependencies", []),
                token_count=tokens_used,
                error_message=None if task_status == "done" else output_content,
                composed_at=None,
            )
            entries = [e for e in entries if e["task_id"] != task_id]
            entries.append(new_entry)
            manifest = {
                **manifest,
                "entries": entries,
                "total_documents": len(entries),
                "total_tokens": sum(e["token_count"] for e in entries),
            }
            manifest_output["document_manifest"] = manifest

            # Emit progressive manifest update so frontend shows documents as they're built
            try:
                await emit_manifest_update(
                    session_id=session_id,
                    manifest_entry={
                        "taskId": task_id,
                        "specSection": spec_section or "Unknown",
                        "status": entry_status,
                        "tokenCount": tokens_used,
                        "sectionType": section_type,
                    },
                    total_documents=len(entries),
                    total_tokens=sum(e["token_count"] for e in entries),
                    client_id=client_id,
                )
            except Exception as e:
                logger.warning(f"WorkerNode emit_manifest_update failed: {e}")

        tokens_used: int = get_token_estimator().count_tokens(output_content) if output_content else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

        task_result = {
            "id": task_id,
            "name": task_name,
            "status": task_status,
            "output": output_content if output_content else "",
            "output_ref": f"orchestrate.{task_id}.draft" if draft_ref else None,
        }

        # Update task results
        task_results = list(orchestrate.get("task_results", []))
        existing_ids = {t.get("id") for t in task_results}
        if task_id in existing_ids:
            task_results = [task_result if t.get("id") == task_id else t for t in task_results]
        else:
            task_results.append(task_result)

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "task_results": task_results,
                    "current_draft": output_content if output_content else "",
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
                **manifest_output,
            }
        )


class CritiqueNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """Reviews worker output via ArchitectAgent.critique_task().

    Calls the ArchitectAgent's critique method instead of raw LLM,
    reusing the agent's quality evaluation logic.

    Requirements: 24.1, 24.2
    """

    CRITERIA = ["completeness", "accuracy", "clarity", "relevance"]

    def __init__(self) -> None:
        super().__init__(node_name="critique")
        self.phase = "orchestrate"
        self.step_name = "critique"
        self.step_progress = 0.80

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")
        budget: BudgetState = state.get("budget", {})

        orchestrate: OrchestrateData = state.get("orchestrate", {})
        current_task = orchestrate.get("current_task", {})
        current_draft: str = orchestrate.get("current_draft", "")

        if not current_task:
            return NodeExecutionResult.success(output={"orchestrate": {**orchestrate, "critique_passed": True}})

        BudgetGuard.check(budget)

        task_id = current_task.get("id", "unknown")
        task_name = current_task.get("name", "Unknown")

        # Build the app_context adapter for the agent
        workflow_context: WorkflowContext | None = configurable.get("context")

        if not workflow_context:
            raise RuntimeError("CritiqueNode requires workflow_context")

        # Build the arguments ArchitectAgent.critique_task() expects
        task_result = {
            "output": current_draft,
            "status": "done" if current_draft else "failed",
            "error": None,
        }
        assignment = {
            "task_id": task_id,
            "task_name": task_name,
            "agent_type": orchestrate.get("assigned_agent", "general"),
            "complexity": orchestrate.get("task_complexity", "unknown"),
        }
        original_context = orchestrate.get("agent_context", {})

        critique: Optional[CritiqueResult] = None
        llm_calls = 0

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="orchestrate",
                step="critique",
                message=f"Reviewing output for task '{task_name}'",
                progress_pct=0.80,
                client_id=client_id,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning(f"CritiqueNode emit_phase_progress failed: {e}")

        try:
            architect = ArchitectAgent()
            critique: CritiqueResult = await architect.critique_task(
                task_result=task_result,
                assignment=assignment,
                original_context=original_context,
                workflow_context=workflow_context,
            )
            llm_calls = 1
        except Exception as e:
            logger.warning(f"CritiqueNode agent call failed: {e}")
            # Do NOT auto-approve on exception — this silently bypasses the quality gate.
            # Instead, mark as not approved with a low score so the critique loop retries
            # or the task proceeds to progress with a visible failure reason.
            critique: CritiqueResult = {
                "approved": False,
                "score": 0.0,
                "feedback": f"Critique unavailable (error: {e}). Output not validated.",
            }
            # Note: llm_calls stays 0 — no LLM call was made when prompt formatting fails

        feedback_text = critique.get("feedback", "") if isinstance(critique, dict) else str(critique)
        tokens_used: int = get_token_estimator().count_tokens(feedback_text) if feedback_text else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

        # Update iteration tracking
        iteration_count = orchestrate.get("iteration_count", 0) + 1
        critique_history = list(orchestrate.get("critique_history", []))
        critique_history.append(
            {
                "task_id": task_id,
                "iteration": iteration_count,
                "verdict": "approve" if critique.get("approved") else "revise",
                "score": critique.get("score", 0.0),
            }
        )

        # Map agent's approved bool → critique_passed routing field
        agent_approved = critique.get("approved", True)
        needs_revision = not agent_approved and iteration_count < 3
        critique_passed = not needs_revision

        # Track consecutive rejections for circuit breaker.
        # Reset to 0 on any approval; increment on rejection.
        consecutive_rejections = orchestrate.get("consecutive_rejections", 0)
        if agent_approved:
            consecutive_rejections = 0
        else:
            consecutive_rejections += 1

        # Store critique via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        if artifact_svc:
            try:
                ref = await artifact_svc.store(
                    "orchestrate",
                    f"tasks/{task_id}/critique_v{iteration_count}.json",
                    json.dumps(critique, indent=2),
                    f"Critique for task {task_id} iteration {iteration_count}",
                )
                artifacts_output[f"orchestrate.{task_id}.critique_v{iteration_count}"] = ref
            except Exception:
                pass  # best-effort

        # Emit plan.task.critique event
        try:
            from graph_kb_api.websocket.plan_events import emit_task_critique

            await emit_task_critique(
                session_id=session_id,
                task_id=task_id,
                passed=critique_passed,
                feedback=critique.get("feedback", ""),
                client_id=client_id,
                task_name=task_name,
                score=critique.get("score"),
                iteration=iteration_count,
            )
        except Exception as e:
            logger.warning(f"CritiqueNode emit_task_critique failed: {e}")

        return NodeExecutionResult.success(
            output={
                "orchestrate": {
                    **orchestrate,
                    "critique_passed": critique_passed,
                    "critique_feedback": critique.get("feedback", ""),
                    "iteration_count": iteration_count,
                    "critique_history": critique_history[-10:],
                    "consecutive_rejections": consecutive_rejections,
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )


class ProgressNode(SubgraphAwareNode[OrchestrateSubgraphState]):
    """
    Emits task-level progress with task_progress field.

    Tracks completed tasks and emits progress events for
    orchestrate subgraph.
    """

    def __init__(self) -> None:
        super().__init__(node_name="progress")
        self.phase = "orchestrate"
        self.step_name = "progress"
        self.step_progress = 1.0

    async def _execute_step(self, state: OrchestrateSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        orchestrate = state.get("orchestrate", {})
        planning = state.get("plan", {})

        task_dag = planning.get("task_dag", {})
        all_tasks = task_dag.get("tasks", [])
        task_results = orchestrate.get("task_results", [])

        total_tasks = len(all_tasks)
        completed_tasks = len([t for t in task_results if t.get("status") == "done"])
        # Count all terminal statuses (done, failed, error) for completion check.
        # Using only "done" caused an infinite loop: if any task failed,
        # finished_count < total_tasks forever and all_complete was never set.
        finished_tasks = len([t for t in task_results if t.get("status") in ("done", "failed", "error")])
        progress_pct = completed_tasks / max(total_tasks, 1)

        all_complete = finished_tasks == total_tasks and total_tasks > 0

        # Store current task final output and append to iteration_log (GAP 12d)
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")
        current_task = orchestrate.get("current_task", {})
        current_draft: str = orchestrate.get("current_draft", "")
        task_id = current_task.get("id", "unknown") if isinstance(current_task, dict) else "unknown"

        critiques = orchestrate.get("critique_history", [])
        agent_approved = critiques[-1].get("passed", True) if critiques else True

        artifacts_output: Dict[str, Any] = {}
        if artifact_svc and current_draft and task_id != "unknown":
            try:
                # Store final task output
                ref = await artifact_svc.store(
                    "orchestrate",
                    f"tasks/{task_id}/final.md",
                    current_draft,
                    f"Final output for task {task_id}",
                )
                artifacts_output[f"orchestrate.tasks.{task_id}.final"] = ref
            except Exception:
                pass  # Best-effort storage

            try:
                # Append to iteration log
                log_entry = json.dumps(
                    {
                        "task_id": task_id,
                        "completed_tasks": completed_tasks,
                        "total_tasks": total_tasks,
                        "progress_pct": progress_pct,
                    },
                    default=str,
                )
                ref = await artifact_svc.store(
                    "orchestrate",
                    "iteration_log.json",
                    log_entry,
                    f"Iteration log entry for task {task_id}",
                )
                artifacts_output["orchestrate.iteration_log"] = ref
            except Exception:
                pass  # Best-effort storage

        # Emit plan.task.complete event
        if task_id != "unknown":
            try:
                from graph_kb_api.websocket.plan_events import emit_task_complete

                await emit_task_complete(
                    session_id=session_id,
                    task_id=task_id,
                    client_id=client_id,
                    artifacts=self._serialize_artifacts(state["artifacts"]),
                    task_name=current_task.get("name", "") if isinstance(current_task, dict) else "",
                    spec_section=current_task.get("spec_section", "") if isinstance(current_task, dict) else "",
                    approved=agent_approved,
                )
            except Exception:
                pass  # fire-and-forget

        # ── Circuit breaker: detect insufficient context ──────────────────
        # If consecutive_rejections >= number of ready tasks in the current
        # cycle, every task has been rejected without a single approval.
        # This means the input context is too thin — continuing will waste
        # LLM budget endlessly. End the phase and surface partial drafts.
        circuit_breaker_triggered = False
        consecutive_rejections = orchestrate.get("consecutive_rejections", 0)
        ready_task_count = len(orchestrate.get("ready_tasks", []))
        # Use total_tasks as fallback when ready_tasks isn't populated
        cycle_size = max(ready_task_count, total_tasks, 1)

        if consecutive_rejections >= cycle_size and total_tasks > 0:
            circuit_breaker_triggered = True
            logger.warning(
                "Circuit breaker triggered: %d consecutive rejections across %d tasks "
                "with 0 approvals. Ending orchestrate phase.",
                consecutive_rejections,
                cycle_size,
            )
            try:
                await emit_circuit_breaker(
                    session_id=session_id,
                    message=(
                        f"Orchestration stopped: all {cycle_size} tasks were rejected by "
                        f"the critique agent due to insufficient specification context. "
                        f"The provided input lacks the detail needed for the agents to "
                        f"produce approved outputs. Please add more context (requirements "
                        f"documents, API specs, constraints) and retry."
                    ),
                    total_tasks=total_tasks,
                    rejected_count=consecutive_rejections,
                    client_id=client_id,
                )
            except Exception as e:
                logger.warning(f"ProgressNode emit_circuit_breaker failed: {e}")

        # Treat circuit breaker as partial completion — mark orchestrate done
        # so the workflow continues to assembly with whatever was produced,
        # rather than halting with an unrecoverable error.
        phase_complete = all_complete or circuit_breaker_triggered

        output: Dict[str, Any] = {
            "orchestrate": {
                **orchestrate,
                "total_tasks": total_tasks,
                "current_task_index": orchestrate.get("current_task_index", 0) + 1,
                "all_complete": all_complete,
                "circuit_breaker_triggered": circuit_breaker_triggered,
            },
            "artifacts": artifacts_output,
        }
        if phase_complete:
            output["completed_phases"] = {"orchestrate": True}
            result_summary = (
                f"All {total_tasks} tasks complete"
                if all_complete
                else (
                    f"Circuit breaker: {completed_tasks}/{total_tasks} tasks approved, "
                    f"{consecutive_rejections} rejected. Continuing with partial results."
                )
            )
            # Emit phase.complete so frontend can mark orchestrate phase done
            try:
                from graph_kb_api.websocket.plan_events import emit_phase_complete

                await emit_phase_complete(
                    session_id=session_id,
                    phase="orchestrate",
                    result_summary=result_summary,
                    duration_s=0.0,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget

        # Persist task_results to DB so they survive server restarts.
        # The orchestrate subgraph runs with use_default_checkpointer=False,
        # meaning the parent LangGraph checkpoint only holds pre-subgraph state.
        # Without this, a restart wipes all completed task progress.
        if session_id and task_results:
            try:
                from graph_kb_api.database.plan_repositories import PlanSessionRepository

                async with get_db_session_ctx() as db_session:
                    repo = PlanSessionRepository(db_session)
                    await repo.update(session_id, task_results=list(task_results))
            except Exception as e:
                logger.warning("ProgressNode: failed to persist task_results to DB: %s", e)

        return NodeExecutionResult.success(output=output)
