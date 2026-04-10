"""OrchestrateSubgraph -- architect-led critique loop with task dispatch."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.plan_subgraphs.plan_subgraph_base import PlanSubgraph
from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import (
    CritiqueNode,
    DispatchNode,
    FetchContextNode,
    ProgressNode,
    TaskContextInputNode,
    TaskResearchNode,
    TaskSelectorNode,
    ToolPlanNode,
    WorkerNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import OrchestrateSubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class OrchestrateSubgraph(PlanSubgraph):
    """Architect-led critique loop with task dispatch and per-task research.

    Conditional routing flow:
        START -> task_selector -> fetch_context -> task_context_input ->
        task_research -> tool_plan -> dispatch -> worker -> critique ->
        (worker | progress) -> (task_selector | END)
    """

    def __init__(self, workflow_context: WorkflowContext) -> None:
        super().__init__(workflow_context, "orchestrate_subgraph")

    def _initialize_nodes(self) -> None:
        self.task_selector = TaskSelectorNode()
        self.fetch_context = FetchContextNode()
        self.task_context_input = TaskContextInputNode()
        self.task_research = TaskResearchNode()
        self.tool_plan = ToolPlanNode()
        self.dispatch = DispatchNode()
        self.worker = WorkerNode()
        self.critique = CritiqueNode()
        self.progress = ProgressNode()
        logger.info("Orchestrate subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        builder = StateGraph(OrchestrateSubgraphState)
        builder.add_node("task_selector", self.task_selector)
        builder.add_node("fetch_context", self.fetch_context)
        builder.add_node("task_context_input", self.task_context_input)
        builder.add_node("task_research", self.task_research)
        builder.add_node("tool_plan", self.tool_plan)
        builder.add_node("dispatch", self.dispatch)
        builder.add_node("worker", self.worker)
        builder.add_node("critique", self.critique)
        builder.add_node("progress", self.progress)
        builder.add_edge(START, "task_selector")
        builder.add_edge("task_selector", "fetch_context")
        builder.add_edge("fetch_context", "task_context_input")
        builder.add_edge("task_context_input", "task_research")
        builder.add_edge("task_research", "tool_plan")
        builder.add_edge("tool_plan", "dispatch")
        builder.add_edge("dispatch", "worker")
        builder.add_edge("worker", "critique")
        builder.add_conditional_edges(
            "critique",
            OrchestrateSubgraph._route_after_critique,
            {"worker": "worker", "progress": "progress"},
        )
        builder.add_conditional_edges(
            "progress",
            OrchestrateSubgraph._route_after_progress,
            {"task_selector": "task_selector", "__end__": END},
        )
        compiled = builder.compile(checkpointer=self.checkpointer)
        logger.info("Orchestrate subgraph compiled")
        return compiled

    # Maximum iterations for the critique loop (Req 0g)
    MAX_CRITIQUE_ITERATIONS = 3

    @staticmethod
    def _route_after_critique(
        state: dict,
    ) -> Literal["worker", "progress"]:
        """Route to worker on critique fail, progress otherwise.

        Skips critique re-loop for failed/error tasks — routes directly
        to progress to avoid critiquing error messages.

        Includes loop guard to prevent infinite critique iterations.
        After MAX_CRITIQUE_ITERATIONS, forces progress regardless of
        critique result.
        """
        # Skip critique loop for failed tasks
        orchestrate = state.get("orchestrate", {})
        current_task = orchestrate.get("current_task", {})
        task_results = orchestrate.get("task_results", [])
        task_id = current_task.get("id", "") if isinstance(current_task, dict) else ""
        task_status = next(
            (t.get("status") for t in task_results if t.get("id") == task_id),
            "done",
        )
        if task_status in ("failed", "error"):
            return "progress"

        critique_passed = orchestrate.get("critique_passed", True)
        if not critique_passed:
            iteration_count = orchestrate.get("iteration_count", 0)
            if iteration_count >= OrchestrateSubgraph.MAX_CRITIQUE_ITERATIONS:
                # Loop guard: force progress after max iterations
                return "progress"
            return "worker"
        return "progress"

    # Maximum outer-loop iterations to prevent infinite cycling (task_selector → progress).
    # Each cycle processes one task. If exceeded, the loop is stuck (blocked tasks,
    # repeated failures, etc.) and we force completion.
    MAX_TASK_LOOP_ITERATIONS = 500

    @staticmethod
    def _route_after_progress(
        state: dict,
    ) -> Literal["task_selector", "__end__"]:
        """Route back to task_selector for next task, or END if all tasks complete.

        Checks orchestrate.all_complete, circuit breaker, blocked state, and a
        loop guard to prevent infinite cycling when tasks are stuck or
        repeatedly failing.
        """
        orchestrate = state.get("orchestrate", {})
        all_complete = orchestrate.get("all_complete", False)
        if all_complete:
            return "__end__"
        # Circuit breaker: all tasks rejected in a full cycle with 0 approvals
        if orchestrate.get("circuit_breaker_triggered", False):
            logger.warning(
                "Orchestrate loop: circuit breaker triggered, ending subgraph"
            )
            return "__end__"
        # Break loop when all remaining tasks are blocked by unmet dependencies
        blocked = orchestrate.get("blocked", False)
        if blocked:
            logger.warning(
                "Orchestrate loop: tasks are blocked (unmet dependencies), ending subgraph"
            )
            return "__end__"
        # Safety net: prevent infinite loop from repeated failures or stale state
        current_task_index = orchestrate.get("current_task_index", 0)
        if current_task_index >= OrchestrateSubgraph.MAX_TASK_LOOP_ITERATIONS:
            logger.warning(
                "Orchestrate loop: hit max iterations (%d), forcing END",
                OrchestrateSubgraph.MAX_TASK_LOOP_ITERATIONS,
            )
            return "__end__"
        return "task_selector"


__all__ = ["OrchestrateSubgraph"]
