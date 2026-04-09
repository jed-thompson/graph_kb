"""
SubgraphAwareNode — required base class for ALL plan nodes.

Extends BaseWorkflowNodeV3 with automatic progress emission on node entry.
Subclasses implement _execute_step() instead of _execute_async().
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any, Dict, Generic, TypeVar, cast

from langgraph.errors import GraphInterrupt
from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.database.base import get_db_session_ctx
from graph_kb_api.database.plan_models import PlanSession
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import ThreadConfigurable
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.services.artifact_service import ArtifactStorageError
from graph_kb_api.flows.v3.services.budget_guard import BudgetExhaustedError, BudgetGuard
from graph_kb_api.flows.v3.state import ContextData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import (
    ApprovalInterruptPayload,
    ArtifactManifestEntry,
    ArtifactRef,
    TransitionEntry,
)
from graph_kb_api.websocket.plan_events import emit_budget_warning, emit_error, emit_phase_enter

logger = logging.getLogger(__name__)


S = TypeVar("S")


class SubgraphAwareNode(BaseWorkflowNodeV3, Generic[S]):
    """Base class for nodes that emit subgraph-level progress.

    REQUIRED base class for ALL plan nodes.

    Attributes:
        phase: The workflow phase this node belongs to (e.g. "orchestrate", "research").
        step_name: The step identifier within the phase (e.g. "budget_check").
        step_progress: Position within the subgraph as a float from 0.0 to 1.0.
    """

    phase: str
    step_name: str
    step_progress: float
    skip_auto_progress: bool = False

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """Auto-emit progress on entry, then delegate to _execute_step.

        Retrieves the progress callback from config["configurable"] and emits
        a progress event before calling the subclass's _execute_step method.
        After execution, appends a TransitionEntry to the result output for
        the transition_log (append-only via operator.add reducer).

        If _execute_step raises BudgetExhaustedError, this method catches it,
        emits a budget warning event, and triggers a HITL interrupt so the
        user can choose to increase the budget, accept current results, or
        cancel (Requirements 28.1, 28.2, 28.3).

        If _execute_step raises ArtifactStorageError (after all retries
        exhausted), this method catches it, emits a spec.error event with
        code=STORAGE_ERROR, and returns a result that pauses the workflow
        (workflow_status="paused", paused_phase=current phase) so the user
        can retry after the storage issue is resolved.
        """
        config: RunnableConfig = cast(RunnableConfig, getattr(self, "_config", None) or {})
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        progress_cb = configurable.get("progress_callback")

        # Emit plan.phase.enter only for the first step in the phase (step_progress == 0.0)
        # This prevents emitting on every node — only the entry node triggers it (Req 0h)
        if self.step_progress == 0.0:
            completed_phases = state.get("completed_phases", {})
            if not completed_phases.get(self.phase):
                try:
                    session_id = state.get("session_id", "")
                    client_id: str | None = configurable.get("client_id")
                    await emit_phase_enter(
                        session_id=session_id,
                        phase=self.phase,
                        expected_steps=1,  # Default; subgraphs can override
                        client_id=client_id,
                    )
                except Exception:
                    pass  # Fire-and-forget (Req 29.2)

        if progress_cb and not self.skip_auto_progress:
            try:
                await progress_cb(
                    {
                        "session_id": state.get("session_id", ""),
                        "phase": self.phase,
                        "step": self.step_name,
                        "message": f"{self.step_name}...",
                        "percent": self.step_progress,
                    }
                )
            except Exception:
                pass  # Fire-and-forget: silently drop on disconnect (Req 29.2)

        try:
            # Set LLM recording context so LLMService can tag recordings
            # with the current step/phase (zero changes needed in individual nodes).
            from graph_kb_api.core.llm_recorder import _llm_call_context

            _ctx_token = _llm_call_context.set({"step": self.step_name, "phase": self.phase})
            try:
                result: NodeExecutionResult = await self._execute_step(cast(S, state), config)
            finally:
                _llm_call_context.reset(_ctx_token)
        except BudgetExhaustedError as exc:
            # Emit budget exhaustion progress event (Req 28.1)
            if progress_cb:
                try:
                    await progress_cb(
                        {
                            "session_id": state.get("session_id", ""),
                            "phase": self.phase,
                            "step": self.step_name,
                            "message": f"Budget exhausted: {exc}",
                            "percent": self.step_progress,
                        }
                    )
                except Exception:
                    pass  # Fire-and-forget (Req 29.2)
            # Emit budget warning so frontend BudgetIndicator shows warning state
            try:
                session_id = state.get("session_id", "")
                client_id: str | None = configurable.get("client_id")
                budget = state.get("budget", {})
                remaining_calls = budget.get("remaining_llm_calls", 0)
                max_calls = budget.get("max_llm_calls", 1)
                remaining_pct = max(remaining_calls / max(max_calls, 1), 0.0)
                await emit_budget_warning(
                    session_id=session_id,
                    remaining_pct=remaining_pct,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget

            # Use interrupt() for HITL — user can increase budget or accept results
            payload: ApprovalInterruptPayload = {
                "type": "approval",
                "phase": self.phase,
                "step": self.step_name,
                "summary": {
                    "budget_exhausted": True,
                    "reason": str(exc),
                    "remaining_llm_calls": state.get("budget", {}).get("remaining_llm_calls", 0),
                    "tokens_used": state.get("budget", {}).get("tokens_used", 0),
                    "max_llm_calls": state.get("budget", {}).get("max_llm_calls", 0),
                    "max_tokens": state.get("budget", {}).get("max_tokens", 0),
                },
                "message": (
                    f"Budget exhausted during {self.phase}/{self.step_name}: {exc}. "
                    "Increase budget to continue, or accept current results."
                ),
                "options": [
                    {"id": "increase_budget", "label": "Increase Budget & Continue"},
                    {"id": "accept_results", "label": "Accept Current Results"},
                    {"id": "cancel", "label": "Cancel"},
                ],
                "artifacts": self._serialize_artifacts(cast(dict[str, ArtifactRef], state.get("artifacts", {}))),
                # Snapshot completed task_results and document_manifest so
                # handle_reconnect / handle_phase_input can restore them
                # after page refresh or budget resume (parent checkpoint lacks
                # orchestrate subgraph state when use_default_checkpointer=False).
                "task_results": list(state.get("orchestrate", {}).get("task_results") or []),
                "document_manifest": state.get("document_manifest"),
            }
            response = interrupt(payload)

            # Handle the user's response after resume
            decision = response.get("decision", "accept_results")
            if decision == "cancel":
                return NodeExecutionResult.success(
                    output={
                        "workflow_status": "cancelled",
                        "paused_phase": self.phase,
                        "error": {
                            "message": f"Budget exhausted and user cancelled: {exc}",
                            "code": "BUDGET_CANCELLED",
                            "phase": self.phase,
                        },
                    }
                )
            if decision == "accept_results":
                if self.phase == "assembly":
                    completed_phases = dict(state.get("completed_phases", {}))
                    completed_phases["assembly"] = True
                    completeness = dict(state.get("completeness", {}))
                    completeness.update(
                        {
                            "approved": True,
                            "approval_decision": "approve",
                            "accepted_budget_exhausted_results": True,
                            "budget_exhausted_reason": str(exc),
                        }
                    )
                    return NodeExecutionResult.success(
                        output={
                            "workflow_status": "running",
                            "completed_phases": completed_phases,
                            "completeness": completeness,
                        }
                    )
                return NodeExecutionResult.success(
                    output={
                        "workflow_status": "budget_exhausted",
                        "paused_phase": self.phase,
                        "completed_phases": state.get("completed_phases", {}),
                        "error": {
                            "message": f"Budget exhausted during {self.phase}/{self.step_name}: {exc}",
                            "code": "BUDGET_EXHAUSTED",
                            "phase": self.phase,
                        },
                    }
                )
            # decision == "increase_budget": budget was updated via
            # aupdate_state on the parent graph, but the subgraph is
            # resumed mid-execution so its internal state still has the
            # old exhausted values. Propagate the budget_update (computed
            # by plan_dispatcher and injected into resume data) into the
            # subgraph state via this node's output.
            budget_update = response.get("budget_update")
            if budget_update:
                updated_budget = {**(state.get("budget") or {}), **budget_update}
                return NodeExecutionResult.success(
                    output={"budget": updated_budget, "workflow_status": "running"},
                )
            # budget_update missing — apply a default increase so the
            # workflow does not immediately re-exhaust on the next check.
            fallback_budget = BudgetGuard.increase(
                state.get("budget") or {},
                reset_wall_clock=True,
            )
            return NodeExecutionResult.success(
                output={"budget": fallback_budget, "workflow_status": "running"},
            )
        except ArtifactStorageError as exc:
            # Emit spec.error with STORAGE_ERROR code (Req 27.2)
            try:
                session_id = state.get("session_id", "")
                client_id: str | None = configurable.get("client_id")
                await emit_error(
                    session_id=session_id,
                    message=(f"Storage failure during {self.phase}/{self.step_name}: {exc}"),
                    code="STORAGE_ERROR",
                    phase=self.phase,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget

            return NodeExecutionResult.success(
                output={
                    "workflow_status": "paused",
                    "paused_phase": self.phase,
                    "error": {
                        "message": f"Storage failure: {exc}",
                        "code": "STORAGE_ERROR",
                        "phase": self.phase,
                    },
                }
            )
        except GraphInterrupt:
            # GraphInterrupt is raised by interrupt() for human-in-the-loop.
            # Must propagate to LangGraph so the workflow pauses correctly.
            raise
        except (RuntimeError, ValueError) as exc:
            # Propagate node-level errors (missing LLM, invalid state, etc.)
            # so the graph handles them properly instead of silently continuing.
            logger.error(f"[{self.phase}/{self.step_name}] Raising node error: {exc}")
            try:
                session_id = state.get("session_id", "")
                client_id: str | None = configurable.get("client_id")
                await emit_error(
                    session_id=session_id,
                    message=(f"Execution failed during {self.phase}/{self.step_name}: {exc}"),
                    code="NODE_EXECUTION_ERROR",
                    phase=self.phase,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget
            raise
        except Exception as exc:
            # Catch all other unhandled LLM or Node execution errors.
            # Emit error to WebSocket, then RE-RAISE so LangGraph halts
            # instead of continuing with corrupted state.
            logger.error(
                f"[{self.phase}/{self.step_name}] Unhandled exception: {exc}",
                exc_info=True,
            )
            try:
                session_id = state.get("session_id", "")
                client_id: str | None = configurable.get("client_id")
                await emit_error(
                    session_id=session_id,
                    message=(f"Execution failed during {self.phase}/{self.step_name}: {exc}"),
                    code="NODE_EXECUTION_ERROR",
                    phase=self.phase,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget
            raise

        # Append a TransitionEntry to the output for the transition_log reducer
        budget = state.get("budget") or {}
        transition: TransitionEntry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "from_node": self.step_name,
            "to_node": "next",
            "subgraph": self.phase,
            "reason": "step_complete",
            "budget_snapshot": {
                "remaining_llm_calls": budget.get("remaining_llm_calls", 0),
                "tokens_used": budget.get("tokens_used", 0),
            },
        }
        if "transition_log" not in result.output:
            result.output["transition_log"] = []
        result.output["transition_log"].append(transition)

        return result

    @abstractmethod
    async def _execute_step(self, state: S, config: RunnableConfig) -> NodeExecutionResult:
        """Execute the node's core logic.

        Subclasses MUST implement this method instead of _execute_async.

        Args:
            state: Current workflow state.
            config: LangGraph RunnableConfig with configurable services.

        Returns:
            NodeExecutionResult with the execution outcome.
        """
        raise NotImplementedError("Subclasses must implement _execute_step")

    # ------------------------------------------------------------------
    # Shared serialization helpers used by multiple plan node classes
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_content_type(artifact_name: str) -> str:
        """Infer MIME content type from artifact file extension."""
        if artifact_name.endswith(".json"):
            return "application/json"
        elif artifact_name.endswith(".md"):
            return "text/markdown"
        elif artifact_name.endswith(".jsonl"):
            return "application/jsonl"
        return "text/plain"

    @staticmethod
    def _serialize_artifacts(artifacts: dict[str, ArtifactRef]) -> list[ArtifactManifestEntry]:
        """Convert PlanState.artifacts dict to a frontend-friendly manifest list.

        Strips the ``specs/{session_id}/`` prefix from each key so the
        frontend can pass the short key directly to ``GET /plan/sessions/{id}/artifacts/{key}``.
        """
        entries: list[ArtifactManifestEntry] = []
        for name, ref in artifacts.items():
            short_key = ref["key"]
            # Strip "specs/{session_id}/" prefix → e.g. "research/full_findings.json"
            if "/" in short_key:
                short_key = short_key.split("/", 2)[-1]
            entry: ArtifactManifestEntry = {
                "key": short_key,
                "summary": ref["summary"],
                "size_bytes": ref["size_bytes"],
                "created_at": ref["created_at"],
                "content_type": SubgraphAwareNode._infer_content_type(short_key),
            }
            entries.append(entry)
        return entries

    @staticmethod
    async def _load_context_items(
        session_id: str | None,
        research: ResearchData,
        context: ContextData | None = None,
    ) -> dict[str, Any]:
        """Load persisted context_items from DB, falling back to empty dict.

        Reads context_items that FeedbackReviewNode persisted to the plan session,
        and merges in any research findings doc IDs from artifacts.
        Also merges uploaded document IDs from context state when provided.
        """
        context_items: dict[str, Any] = {}
        if session_id:
            try:
                from graph_kb_api.database.plan_repositories import PlanSessionRepository

                async with get_db_session_ctx() as db_session:
                    repo = PlanSessionRepository(db_session)
                    session: PlanSession | None = await repo.get(session_id)
                    if session and session.context_items:
                        context_items = dict(session.context_items)
            except Exception as e:
                logger.warning("Failed to load context_items: %s", e)

        # Normalize DB context_items: _persist_runtime_snapshot may have overwritten
        # FeedbackReviewNode's canonical DB write with raw ContextData that uses
        # form-field keys (primary_document, supporting_docs) instead of canonical
        # keys (primary_document_id, supporting_doc_ids).
        primary_doc_id_db = (
            context_items.get("primary_document_id") or context_items.get("primary_document") or ""
        )
        if primary_doc_id_db and not context_items.get("primary_document_id"):
            context_items["primary_document_id"] = primary_doc_id_db
        supporting_ids_db: list[str] = list(context_items.get("supporting_doc_ids") or [])
        form_supporting_db = context_items.get("supporting_docs") or []
        if isinstance(form_supporting_db, str):
            form_supporting_db = [s.strip() for s in form_supporting_db.split(",") if s.strip()]
        elif not isinstance(form_supporting_db, list):
            form_supporting_db = []
        for doc_id in form_supporting_db:
            if doc_id and doc_id not in supporting_ids_db:
                supporting_ids_db.append(doc_id)
        if supporting_ids_db:
            context_items["supporting_doc_ids"] = supporting_ids_db

        # Merge any research doc IDs from research state
        research_doc_id: str | None = research.get("findings_doc_id")
        if research_doc_id:
            supporting = list(context_items.get("supporting_doc_ids", []))
            if research_doc_id not in supporting:
                supporting.append(research_doc_id)
                context_items["supporting_doc_ids"] = supporting

        # Merge uploaded document IDs from context state so approval gates
        # always show the full document set regardless of whether the DB
        # context_items were persisted before the uploads were associated.
        # Handle both canonical (primary_document_id) and form-field (primary_document) keys
        # since CollectContextNode outputs form-field keys to state.
        if context:
            ctx_dict = cast(Dict[str, Any], context)
            primary_doc_id: str = (
                ctx_dict.get("primary_document_id") or ctx_dict.get("primary_document") or ""
            )
            if primary_doc_id and not context_items.get("primary_document_id"):
                context_items["primary_document_id"] = primary_doc_id

            ctx_supporting: list[str] = list(ctx_dict.get("supporting_doc_ids") or [])
            form_sup = ctx_dict.get("supporting_docs") or []
            if isinstance(form_sup, str):
                form_sup = [s.strip() for s in form_sup.split(",") if s.strip()]
            elif not isinstance(form_sup, list):
                form_sup = []
            for doc_id in form_sup:
                if doc_id and doc_id not in ctx_supporting:
                    ctx_supporting.append(doc_id)
            if ctx_supporting:
                existing_supporting = list(context_items.get("supporting_doc_ids", []))
                for doc_id in ctx_supporting:
                    if doc_id not in existing_supporting:
                        existing_supporting.append(doc_id)
                context_items["supporting_doc_ids"] = existing_supporting

        return context_items
