"""PlanEngine — parent graph composing 5 plan subgraphs.

Linear flow with prune nodes between subgraphs:
    context → research → prune_after_research → planning →
    orchestrate → prune_after_orchestrate → assembly → finalize

Extends BaseWorkflowEngine with plan-specific subgraph composition,
budget initialization, and service injection via WorkflowContext.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, Optional, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, RunnableConfig, StateSnapshot

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.graphs.plan_subgraphs.assembly_subgraph import (
    AssemblySubgraph,
)
from graph_kb_api.flows.v3.graphs.plan_subgraphs.context_subgraph import (
    ContextSubgraph,
)
from graph_kb_api.flows.v3.graphs.plan_subgraphs.orchestrate_subgraph import (
    OrchestrateSubgraph,
)
from graph_kb_api.flows.v3.graphs.plan_subgraphs.planning_subgraph import (
    PlanningSubgraph,
)
from graph_kb_api.flows.v3.graphs.plan_subgraphs.research_subgraph import (
    ResearchSubgraph,
)
from graph_kb_api.flows.v3.models.types import ThreadConfigurable
from graph_kb_api.flows.v3.nodes.plan_nodes import (
    FinalizeNode,
    PruneAfterOrchestrateNode,
    PruneAfterResearchNode,
)
from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import CASCADE_MAP, PlanPhase, PlanState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class PlanEngine(BaseWorkflowEngine):
    """Parent graph composing 5 plan subgraphs.

    Composes subgraphs in linear flow with prune nodes:
        context → research → prune_after_research → planning →
        orchestrate → prune_after_orchestrate → assembly → finalize

    Subgraphs are added as compiled graphs via
    ``builder.add_node(name, self.subgraph.workflow)``.
    All services are accessed via WorkflowContext.
    """

    def __init__(self, workflow_context: WorkflowContext) -> None:
        """Initialize PlanEngine with WorkflowContext.

        Args:
            workflow_context: Container with all workflow dependencies including
                LLM, artifact_service, blob_storage, checkpointer, and app_context.
        """
        super().__init__(
            workflow_context=workflow_context,
            max_iterations=1,
            workflow_name="plan_engine",
            use_default_checkpointer=True,
        )

    # ── BaseWorkflowEngine Implementation ─────────────────────────────

    def _initialize_tools(self) -> list:
        """No standalone tools — subgraphs handle their own tooling."""
        return []

    def _initialize_nodes(self) -> None:
        """Instantiate all 5 subgraphs, prune nodes, and review gates."""
        self.context_subgraph = ContextSubgraph(workflow_context=self.workflow_context)
        self.research_subgraph = ResearchSubgraph(workflow_context=self.workflow_context)
        self.planning_subgraph = PlanningSubgraph(workflow_context=self.workflow_context)
        self.orchestrate_subgraph = OrchestrateSubgraph(workflow_context=self.workflow_context)
        self.assembly_subgraph = AssemblySubgraph(workflow_context=self.workflow_context)

        # Prune nodes between subgraphs
        self.prune_after_research = PruneAfterResearchNode()
        self.prune_after_orchestrate = PruneAfterOrchestrateNode()

        # Finalize node after assembly
        self.finalize = FinalizeNode()

        logger.info("PlanEngine nodes initialized (5 subgraphs + 2 prune nodes + finalize)")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the parent graph with linear subgraph flow."""
        builder = StateGraph(PlanState)

        # Add subgraphs as compiled graphs
        builder.add_node("context", self.context_subgraph.workflow)
        builder.add_node("research", self.research_subgraph.workflow)
        builder.add_node("prune_after_research", self.prune_after_research)
        builder.add_node("planning", self.planning_subgraph.workflow)
        builder.add_node("orchestrate", self.orchestrate_subgraph.workflow)
        builder.add_node("prune_after_orchestrate", self.prune_after_orchestrate)
        builder.add_node("assembly", self.assembly_subgraph.workflow)
        builder.add_node("finalize", self.finalize)
        builder.add_node("halt_on_incomplete", self._halt_on_phase_incomplete)

        # Linear flow with prune nodes between subgraphs
        builder.add_edge(START, "context")
        builder.add_conditional_edges(
            "context",
            PlanEngine._route_after_context,
            {"research": "research", "__end__": END, "halt_on_incomplete": "halt_on_incomplete"},
        )
        builder.add_conditional_edges(
            "research",
            PlanEngine._route_after_research,
            {
                "prune_after_research": "prune_after_research",
                "__end__": END,
                "halt_on_incomplete": "halt_on_incomplete",
            },
        )
        builder.add_edge("prune_after_research", "planning")
        builder.add_conditional_edges(
            "planning",
            PlanEngine._route_after_planning,
            {"orchestrate": "orchestrate", "__end__": END, "halt_on_incomplete": "halt_on_incomplete"},
        )
        builder.add_conditional_edges(
            "orchestrate",
            PlanEngine._route_after_orchestrate,
            {
                "prune_after_orchestrate": "prune_after_orchestrate",
                "__end__": END,
                "halt_on_incomplete": "halt_on_incomplete",
            },
        )
        builder.add_edge("prune_after_orchestrate", "assembly")
        builder.add_conditional_edges(
            "assembly",
            PlanEngine._route_after_assembly,
            {"finalize": "finalize", "__end__": END, "halt_on_incomplete": "halt_on_incomplete"},
        )
        builder.add_edge("finalize", END)

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("PlanEngine workflow compiled")

        return compiled

    @staticmethod
    def _should_halt(state: dict) -> bool:
        """Check if workflow_status indicates the graph should stop.

        Handles budget_exhausted, paused, rejected, and error statuses
        that nodes return as NodeExecutionResult.success but which
        should prevent further execution.
        """
        status = state.get("workflow_status", "running")
        return status in ("budget_exhausted", "paused", "rejected", "error")

    @staticmethod
    def _route_after_context(state: dict) -> str:
        if PlanEngine._should_halt(state):
            return "__end__"
        if not state.get("completed_phases", {}).get("context"):
            logger.warning("context subgraph ended without completing — halting workflow")
            return "halt_on_incomplete"
        return "research"

    @staticmethod
    def _route_after_research(state: dict) -> str:
        if PlanEngine._should_halt(state):
            return "__end__"
        if not state.get("completed_phases", {}).get("research"):
            logger.warning("research subgraph ended without completing — halting workflow")
            return "halt_on_incomplete"
        return "prune_after_research"

    @staticmethod
    def _route_after_planning(state: dict) -> str:
        if PlanEngine._should_halt(state):
            return "__end__"
        if not state.get("completed_phases", {}).get("planning"):
            logger.warning("planning subgraph ended without completing — halting workflow")
            return "halt_on_incomplete"
        return "orchestrate"

    @staticmethod
    def _route_after_orchestrate(state: dict) -> str:
        if PlanEngine._should_halt(state):
            return "__end__"
        if not state.get("completed_phases", {}).get("orchestrate"):
            logger.warning("orchestrate subgraph ended without completing — halting workflow")
            return "halt_on_incomplete"
        return "prune_after_orchestrate"

    @staticmethod
    def _route_after_assembly(state: dict) -> str:
        """Route after assembly subgraph completes.

        If the user rejected the document, end the workflow without finalizing.
        If workflow_status indicates a halt condition, end early.
        If the assembly phase didn't complete, halt.
        If composition review flagged issues needing re-orchestration, re-enter orchestrate.
        Otherwise proceed to finalize.
        """
        if PlanEngine._should_halt(state):
            return "__end__"
        if not state.get("completed_phases", {}).get("assembly"):
            logger.warning("assembly subgraph ended without completing — halting workflow")
            return "halt_on_incomplete"

        # Check for composition review re-orchestration (Step 16)
        re_execute_ids = state.get("re_execute_task_ids", [])
        if state.get("needs_re_orchestrate", False) and re_execute_ids:
            logger.info(
                f"Composition review flagged {len(re_execute_ids)} tasks "
                f"for re-execution: {re_execute_ids}"
            )
            return "prune_after_orchestrate"

        completeness = state.get("completeness", {})
        decision = completeness.get("approval_decision", "approve")
        if decision == "reject":
            return "__end__"
        return "finalize"

    async def _halt_on_phase_incomplete(self, state: dict, config: RunnableConfig) -> dict:
        """Set error state when a subgraph ends without completing.

        Emits ``plan.error`` so the frontend can display the failure reason
        instead of silently stopping with no feedback.
        """
        import asyncio

        session_id = state.get("session_id", "")
        configurable: ThreadConfigurable = cast(ThreadConfigurable, (config or {}).get("configurable", {}))
        client_id: str = configurable.get("client_id", "")

        # Determine which phase failed by finding the first uncompleted phase
        completed = state.get("completed_phases", {}) or {}
        phase_order = ["context", "research", "planning", "orchestrate", "assembly"]
        failed_phase = "unknown"
        for phase in phase_order:
            if not completed.get(phase):
                failed_phase = phase
                break

        error_msg = f"{failed_phase} phase ended without completing"

        async def _emit() -> None:
            try:
                from graph_kb_api.websocket.plan_events import emit_error

                await emit_error(
                    session_id=session_id,
                    message=error_msg,
                    code="PHASE_INCOMPLETE",
                    phase=failed_phase,
                    client_id=client_id,
                )
            except Exception:
                pass

        asyncio.ensure_future(_emit())

        return {"workflow_status": "error"}

    def _build_initial_state(self, seed: dict[str, Any]) -> dict[str, Any]:
        """Build initial state with BudgetState initialization.

        Initializes remaining_llm_calls to max_llm_calls, tokens_used to 0,
        and started_at to current ISO timestamp.

        Args:
            seed: Initial state values from the caller.

        Returns:
            Complete initial state dict with budget, artifacts, and tracking fields.

        """
        return {
            **seed,
            "budget": {
                "max_llm_calls": seed.get("max_llm_calls", 200),
                "remaining_llm_calls": seed.get("max_llm_calls", 200),
                "max_tokens": seed.get("max_tokens", 500_000),
                "tokens_used": 0,
                "max_wall_clock_s": seed.get("max_wall_clock_s", 1800),
                "started_at": datetime.now(UTC).isoformat(),
            },
            "artifacts": {},
            "transition_log": [],
            "fingerprints": {},
            "completed_phases": {},
            "document_manifest": None,
            "navigation": {},
            "workflow_status": "running",
        }

    async def get_workflow_state(self, config: Optional[RunnableConfig] = None) -> Optional[Dict[str, Any]]:
        """Return the current workflow state values, or ``None`` if no checkpoint exists."""
        effective_config: RunnableConfig = config if config is not None else {}
        snapshot: StateSnapshot = await self.workflow.aget_state(effective_config)
        return snapshot.values if snapshot else None

    def validate_thread_config(self, config: RunnableConfig) -> bool:
        """Verify that *config* contains a valid, non-empty ``thread_id``.

        Prevents accidental cross-session state access by ensuring every
        engine invocation is scoped to a specific thread.

        Parameters
        ----------
        config:
            LangGraph ``RunnableConfig`` to validate.

        Returns
        -------
        ``True`` if the config has a non-empty ``thread_id``, ``False`` otherwise.

        """
        configurable = (config or {}).get("configurable", {})
        thread_id = configurable.get("thread_id")
        return bool(thread_id)

    async def start_workflow(
        self,
        user_query: str,
        user_id: str,
        session_id: str,
        config: RunnableConfig | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Start a new plan workflow.

        Parameters
        ----------
        user_query:
            The spec name (routed to initial_state["context"]["spec_name"]).
        user_id:
            User identifier.
        session_id:
            Session identifier for checkpointing.
        config:
            LangGraph ``RunnableConfig`` (must include
            ``configurable.thread_id`` for checkpointing).
        **kwargs:
            Additional parameters. Pass ``initial_state`` to provide seed state.

        Returns
        -------
        The workflow result dict (or the state at the first interrupt).

        Raises
        ------
        ValueError
            If *config* does not contain a valid ``thread_id``.

        """
        cfg: RunnableConfig = cast(RunnableConfig, config or {})
        if not self.validate_thread_config(cfg):
            raise ValueError("config must include a non-empty configurable.thread_id for session isolation.")

        # Build initial state from kwargs or create default
        initial_state = kwargs.get("initial_state", {})
        if "context" not in initial_state:
            initial_state["context"] = {}
        initial_state["context"].setdefault("spec_name", user_query)
        initial_state.setdefault("session_id", session_id)
        initial_state.setdefault("user_id", user_id)

        state = self._build_initial_state(initial_state)

        logger.info(
            "Starting plan workflow",
            extra={"session_id": state.get("session_id", "")},
        )

        return await self.compiled_workflow.ainvoke(state, config=cfg)

    # Mapping from phase name to state data keys that must be cleared
    # when navigating backward to prevent stale data from merging via operator.or_
    _PHASE_DATA_KEYS: dict[PlanPhase, list[str]] = {
        PlanPhase.CONTEXT: ["context"],
        PlanPhase.RESEARCH: ["research"],
        PlanPhase.PLANNING: ["plan"],
        PlanPhase.ORCHESTRATE: ["orchestrate"],
        PlanPhase.ASSEMBLY: ["completeness", "generate"],
    }

    async def analyze_navigate(self, target_phase: str, config: RunnableConfig) -> dict[str, Any]:
        """Compute cascade analysis WITHOUT mutating state.

        Used by the dispatcher to show a cascade confirmation dialog
        before the user commits to navigation.

        Returns:
            Dict with ``target_phase``, ``cleared_phases``, ``dirty_phases``,
            ``content_changed``, and ``estimated_llm_calls``.
        """
        state_snapshot = await self.workflow.aget_state(config)
        state = state_snapshot.values if state_snapshot else {}

        fingerprints = state.get("fingerprints", {})
        downstream: list[PlanPhase] = CASCADE_MAP.get(PlanPhase(target_phase), [])

        phase_data = state.get(target_phase, {})
        current_hash = FingerprintTracker.compute_phase_data_fingerprint(target_phase, phase_data)
        stored_fp = fingerprints.get(target_phase, {})
        content_changed = stored_fp.get("input_hash") != current_hash if stored_fp else True

        if content_changed:
            dirty_phases = FingerprintTracker.get_dirty_phases(fingerprints, target_phase, CASCADE_MAP)
            cleared: dict[str, bool] = {target_phase: False}
            for phase in downstream:
                cleared[phase] = False
        else:
            dirty_phases: list[str] = []
            cleared = {target_phase: False}

        estimated_llm_calls = 0
        transition_log = state.get("transition_log", [])
        phases_to_recompute = [target_phase] + dirty_phases
        for entry in transition_log:
            if entry.get("subgraph") in phases_to_recompute:
                estimated_llm_calls += 1

        return {
            "target_phase": target_phase,
            "cleared_phases": list(cleared.keys()),
            "dirty_phases": dirty_phases,
            "content_changed": content_changed,
            "estimated_llm_calls": estimated_llm_calls,
        }

    async def navigate_to_phase(self, target_phase: str, config: RunnableConfig) -> dict[str, Any]:
        """Navigate backward to *target_phase*, invalidating downstream phases.

        Calls ``analyze_navigate`` for read-only analysis, then mutates
        state with ``aupdate_state`` to clear completed_phases AND stale
        phase data, and redirects the graph via ``Command(goto=...)``.

        Args:
            target_phase: The phase to navigate back to (e.g. "research").
            config: LangGraph runnable config with thread_id etc.

        Returns:
            Same dict as ``analyze_navigate``.
        """
        analysis = await self.analyze_navigate(target_phase, config)

        cleared_phases = analysis["cleared_phases"]
        cleared: dict[str, bool] = {p: False for p in cleared_phases}

        # Also reset phase-specific data keys to prevent stale data
        # from merging with new subgraph output via operator.or_
        update: dict[str, Any] = {
            "completed_phases": cleared,
            # Reset workflow_status so the graph can run after navigation
            # from a halted state (rejected, error, paused). The reducer
            # allows "running" to override halt statuses for navigation only.
            "workflow_status": "running",
        }
        for phase_name in cleared_phases:
            for key in self._PHASE_DATA_KEYS.get(PlanPhase(phase_name), []):
                update[key] = {}

        logger.info(
            "PlanEngine.navigate_to_phase: selective cascade",
            extra={
                "target_phase": target_phase,
                "content_changed": analysis["content_changed"],
                "cleared_phases": cleared_phases,
                "dirty_phases": analysis["dirty_phases"],
                "estimated_llm_calls": analysis["estimated_llm_calls"],
            },
        )

        await self.workflow.aupdate_state(
            config,
            Command(goto=target_phase, update=update),
            as_node="__start__",
        )

        return analysis

    async def restart_from_phase(self, target_phase: str, config: RunnableConfig) -> dict[str, Any]:
        """Navigate to *target_phase* and re-execute the graph from there.

        Convenience method that calls ``navigate_to_phase`` to update state
        and redirect the graph, then invokes the workflow to resume execution
        from the target subgraph.

        Args:
            target_phase: The phase to navigate back to (e.g. "research").
            config: LangGraph runnable config with thread_id etc.

        Returns:
            The workflow result dict (or the state at the next interrupt).
        """
        nav_result = await self.navigate_to_phase(target_phase, config)

        logger.info(
            "PlanEngine.restart_from_phase: invoking graph from %s",
            target_phase,
            extra={"cleared_phases": nav_result["cleared_phases"]},
        )

        # Cancel stale interrupts left over from previous phase execution
        # to avoid RuntimeError on resume with multiple pending interrupts.
        await self._cancel_stale_interrupts(config)

        return await self.compiled_workflow.ainvoke(None, config=config)


__all__ = ["PlanEngine"]
