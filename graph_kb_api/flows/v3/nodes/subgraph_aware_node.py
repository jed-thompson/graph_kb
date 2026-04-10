"""
SubgraphAwareNode — required base class for ALL plan nodes.

Extends BaseWorkflowNodeV3 with automatic progress emission on node entry.
Subclasses implement _execute_step() instead of _execute_async().
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Generic, TypeVar, cast

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
from graph_kb_api.flows.v3.utils.artifact_utils import (
    _infer_content_type as infer_content_type,
    serialize_artifacts,
)
from graph_kb_api.flows.v3.utils.context_utils import build_context_items_summary
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator
from graph_kb_api.flows.v3.state import ContextData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import (
    ApprovalInterruptPayload,
    ArtifactManifestEntry,
    ArtifactRef,
    BasePlanSubgraphState,
    BudgetState,
    ContextItemsSummary,
    ProgressEvent,
    TransitionEntry,
)
from graph_kb_api.websocket.plan_events import emit_budget_warning, emit_error, emit_phase_enter

if TYPE_CHECKING:
    from graph_kb_api.context import AppContext
    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

logger = logging.getLogger(__name__)

# Import lazily to avoid circular imports; used in __call__ exception handler
_LLMQuotaExhaustedError: type | None = None


def _get_quota_error_class() -> type:
    global _LLMQuotaExhaustedError
    if _LLMQuotaExhaustedError is None:
        from graph_kb_api.core.llm import LLMQuotaExhaustedError
        _LLMQuotaExhaustedError = LLMQuotaExhaustedError
    return _LLMQuotaExhaustedError


@dataclass(frozen=True, slots=True)
class NodeContext:
    """Bundled config/state values extracted once per node execution.

    Replaces 40+ inline extraction blocks across plan nodes.
    Created via ``SubgraphAwareNode._unpack(state, config)``.
    """

    services: ServiceRegistry
    session_id: str
    budget: BudgetState
    phase: str
    config: RunnableConfig
    configurable: ThreadConfigurable
    llm: LLMService | None
    artifact_service: ArtifactService | None
    workflow_context: WorkflowContext | None
    client_id: str | None
    progress_cb: Callable[[ProgressEvent], Awaitable[None]] | None
    db_session_factory: AppContext | None

    @property
    def require_llm(self) -> LLMService:
        """Return LLM or raise if not configured."""
        if self.llm is None:
            raise RuntimeError("LLM service not available in NodeContext")
        return self.llm

    @property
    def require_artifact_service(self) -> ArtifactService:
        """Return ArtifactService or raise if not configured."""
        if self.artifact_service is None:
            raise RuntimeError("ArtifactService not available in NodeContext")
        return self.artifact_service

    @property
    def require_workflow_context(self) -> WorkflowContext:
        """Return WorkflowContext or raise if not configured."""
        if self.workflow_context is None:
            raise RuntimeError("WorkflowContext not available in NodeContext")
        return self.workflow_context


S = TypeVar("S", bound=BasePlanSubgraphState)


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
        # Also skip on loop iterations (e.g., research gap_check → formulate_queries cycle)
        # by checking if the phase's iteration counter is already > 0.
        if self.step_progress == 0.0:
            completed_phases = state.get("completed_phases", {})
            if not completed_phases.get(self.phase):
                # Detect loop iterations: research and orchestrate subgraphs track
                # iteration counts. If > 0, this is a re-entry, not the first entry.
                phase_data = state.get(self.phase, {})
                is_loop_reentry = (
                    phase_data.get("research_gap_iterations", 0) > 0
                    or phase_data.get("current_task_index", 0) > 0
                )
                if not is_loop_reentry:
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
                auto_event: ProgressEvent = {
                    "session_id": state.get("session_id", ""),
                    "phase": self.phase,
                    "step": self.step_name,
                    "message": f"{self.step_name}...",
                    "percent": self.step_progress,
                }
                await progress_cb(auto_event)
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
                    budget_event: ProgressEvent = {
                        "session_id": state.get("session_id", ""),
                        "phase": self.phase,
                        "step": self.step_name,
                        "message": f"Budget exhausted: {exc}",
                        "percent": self.step_progress,
                    }
                    await progress_cb(budget_event)
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
        except Exception as exc:
            # Catch LLMQuotaExhaustedError without a top-level import (avoids circular deps).
            # Also check __cause__ in case an agent wrapped the quota error in RuntimeError.
            _quota_cls = _get_quota_error_class()
            _is_quota = isinstance(exc, _quota_cls) or (
                isinstance(getattr(exc, "__cause__", None), _quota_cls)
            )
            if _is_quota:
                logger.error("LLM quota exhausted during %s/%s: %s", self.phase, self.step_name, exc)
                try:
                    session_id = state.get("session_id", "")
                    client_id_val: str | None = configurable.get("client_id")
                    await emit_error(
                        session_id=session_id,
                        message=(
                            "LLM API quota exhausted. Please check your billing and plan details "
                            "at your LLM provider, then retry."
                        ),
                        code="LLM_QUOTA_EXHAUSTED",
                        phase=self.phase,
                        client_id=client_id_val,
                    )
                except Exception:
                    pass  # fire-and-forget

                return NodeExecutionResult.success(
                    output={
                        "workflow_status": "error",
                        "error": {
                            "message": (
                                "LLM API quota exhausted. Please add credits to your LLM provider "
                                "account and retry."
                            ),
                            "code": "LLM_QUOTA_EXHAUSTED",
                            "phase": self.phase,
                        },
                    }
                )
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
    # Config/state extraction helper
    # ------------------------------------------------------------------

    def _unpack(self, state: S, config: RunnableConfig) -> NodeContext:
        """Extract commonly needed values from state and config into NodeContext.

        Replaces 40+ inline extraction blocks across plan nodes.
        Handles missing optional fields with sensible defaults.

        Args:
            state: Current subgraph state dict.
            config: LangGraph RunnableConfig with configurable services.

        Returns:
            Populated NodeContext instance.
        """
        configurable: ThreadConfigurable = cast(
            ThreadConfigurable, config.get("configurable", {})
        )
        services: ServiceRegistry = configurable.get("services", {})
        workflow_context: WorkflowContext | None = configurable.get("context")

        # Derive db_session_factory from workflow_context.app_context if available
        db_session_factory: AppContext | None = None
        if workflow_context is not None:
            app_ctx: AppContext | None = getattr(workflow_context, "app_context", None)
            if app_ctx is not None:
                db_session_factory = app_ctx

        # Extract typed fields from configurable.  The underlying dict is
        # ``dict[str, Any]`` (LangGraph's RunnableConfig), so ``.get()``
        # returns ``Any``.  We assign to typed locals so that downstream
        # code benefits from static analysis even though there is no
        # runtime enforcement on the dict values themselves.
        llm: LLMService | None = configurable.get("llm")
        artifact_service: ArtifactService | None = configurable.get("artifact_service")
        client_id: str | None = configurable.get("client_id")
        progress_cb: Callable[[ProgressEvent], Awaitable[None]] | None = configurable.get("progress_callback")

        return NodeContext(
            services=services,
            session_id=state.get("session_id", ""),
            budget=state.get("budget", {}),
            phase=self.phase,
            config=config,
            configurable=configurable,
            llm=llm,
            artifact_service=artifact_service,
            workflow_context=workflow_context,
            client_id=client_id,
            progress_cb=progress_cb,
            db_session_factory=db_session_factory,
        )

    # ------------------------------------------------------------------
    # Progress emission helper
    # ------------------------------------------------------------------

    async def _emit_progress(
        self,
        ctx: NodeContext,
        step_name: str,
        progress_pct: float,
        message: str,
    ) -> None:
        """Emit a progress event, swallowing errors silently.

        Args:
            ctx: NodeContext from _unpack().
            step_name: Step identifier within the phase.
            progress_pct: Progress percentage (0.0 to 1.0).
            message: Human-readable progress message.
        """
        if not ctx.progress_cb:
            return
        try:
            event: ProgressEvent = {
                "session_id": ctx.session_id,
                "phase": self.phase,
                "step": step_name,
                "message": message,
                "percent": progress_pct,
            }
            await ctx.progress_cb(event)
        except Exception:
            logger.warning("Progress emission failed for %s/%s", self.phase, step_name)

    # ------------------------------------------------------------------
    # Budget decrement helper
    # ------------------------------------------------------------------

    def _decrement_budget(
        self,
        budget: BudgetState,
        content: str | dict,
        llm_calls: int = 1,
    ) -> BudgetState:
        """Count tokens in content and decrement budget in one call.

        Args:
            budget: Current budget state.
            content: Content to count tokens for (str or dict serialized to JSON).
            llm_calls: Number of LLM calls to deduct.

        Returns:
            Updated BudgetState dict.
        """
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        tokens_used = get_token_estimator().count_tokens(text)
        return BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

    # ------------------------------------------------------------------
    # Shared serialization helpers used by multiple plan node classes
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_content_type(artifact_name: str) -> str:
        """Infer MIME content type from artifact file extension."""
        return infer_content_type(artifact_name)

    @staticmethod
    def _serialize_artifacts(artifacts: dict[str, ArtifactRef]) -> list[ArtifactManifestEntry]:
        """Convert PlanState.artifacts dict to a frontend-friendly manifest list.

        Thin wrapper around ``serialize_artifacts()`` from
        ``graph_kb_api.flows.v3.utils.artifact_utils`` for backward
        compatibility during migration.
        """
        return serialize_artifacts(artifacts)

    @staticmethod
    async def _load_context_items(
        session_id: str | None,
        research: ResearchData,
        context: ContextData | None = None,
    ) -> ContextItemsSummary:
        """Load persisted context_items from DB and merge with a lightweight context summary.

        Reads context_items that FeedbackReviewNode persisted to the plan session,
        then merges with the lightweight summary produced by
        ``build_context_items_summary`` (which strips bulky fields and merges
        research doc IDs).
        """
        # Build lightweight summary from context state (strips bulky fields,
        # merges research doc IDs).
        summary: ContextItemsSummary = build_context_items_summary(
            session_id,
            research if research else ResearchData(),
            context if context else ContextData(),
        )

        # Load DB-persisted context_items (from FeedbackReviewNode).
        db_items: ContextItemsSummary = ContextItemsSummary()
        if session_id:
            try:
                from graph_kb_api.database.plan_repositories import PlanSessionRepository

                async with get_db_session_ctx() as db_session:
                    repo = PlanSessionRepository(db_session)
                    session: PlanSession | None = await repo.get(session_id)
                    if session and session.context_items:
                        db_items = cast(ContextItemsSummary, dict(session.context_items))
            except Exception as e:
                logger.warning("Failed to load context_items: %s", e)

        # Merge DB items into the summary: DB values fill in gaps but don't
        # overwrite context-state values (which are more up-to-date).
        for key in db_items:
            if key not in summary:
                summary[key] = db_items[key]  # type: ignore[literal-required]

        # Merge supporting doc IDs from DB that may not be in context state
        db_supporting: list[str] = list(db_items.get("supporting_doc_ids", []))
        if db_supporting:
            existing: list[str] = list(summary.get("supporting_doc_ids", []))
            for doc_id in db_supporting:
                if doc_id not in existing:
                    existing.append(doc_id)
            summary["supporting_doc_ids"] = existing

        return summary
