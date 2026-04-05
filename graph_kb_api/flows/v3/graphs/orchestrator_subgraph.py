"""
Orchestrator subgraph - LangGraph StateGraph for task orchestration.

This subgraph handles the internal dispatch logic:
  - Task selection from parallel groups
  - Context retrieval with fallback
  - Proactive gap detection
  - Tool planning/replanning
  - Agent dispatch (single or parallel via Send)

The subgraph is invoked by OrchestratorNode, which transforms state between
the parent workflow state and this subgraph's OrchestratorSubgraphState.
"""

from __future__ import annotations

from typing import Literal, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.context import AppContext
from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.orchestrator import (
    ContextFetchNode,
    DispatcherNode,
    GapCheckerNode,
    TaskSelectorNode,
    ToolPlannerNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.orchestrator import OrchestratorSubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class OrchestratorSubgraph(BaseWorkflowEngine):
    """
    Orchestrator subgraph engine for task dispatch orchestration.

    Extends BaseWorkflowEngine to build a LangGraph StateGraph that handles:
      - Task selection from parallel groups
      - Context retrieval with fallback
      - Proactive gap detection
      - Tool planning/replanning
      - Agent dispatch (single or parallel via Send)

    Node flow:
        START -> task_selector -> context_fetch -> gap_checker -> tool_planner -> dispatcher -> END

    Conditional edges:
        - task_selector → END (no tasks)
        - gap_checker → END (gaps found, parent routes to gap_detector)
        - dispatcher → END (always)
    """

    def __init__(
        self,
        app_context: Optional[AppContext] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ):
        """
        Initialize the orchestrator subgraph.

        Args:
            app_context: Application context (optional for subgraph)
            checkpointer: Optional checkpointer for state persistence
        """
        # Subgraph doesn't need LLM or default checkpointer
        workflow_context = WorkflowContext(
            llm=None,
            app_context=app_context,
            checkpointer=checkpointer,
        )

        super().__init__(
            workflow_context=workflow_context,
            max_iterations=1,
            workflow_name="orchestrator_subgraph",
            use_default_checkpointer=False,
        )

    # ── BaseWorkflowEngine Implementation ─────────────────────────────

    def _initialize_tools(self) -> list:
        """No standalone tools — nodes handle their own tooling."""
        return []

    def _initialize_nodes(self) -> None:
        """Instantiate orchestrator subgraph nodes."""
        self.task_selector = TaskSelectorNode()
        self.context_fetch = ContextFetchNode()
        self.gap_checker = GapCheckerNode()
        self.tool_planner = ToolPlannerNode()
        self.dispatcher = DispatcherNode()

        logger.info("Orchestrator subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the orchestrator subgraph."""
        builder = StateGraph(OrchestratorSubgraphState)

        # Add nodes
        builder.add_node("task_selector", self.task_selector)
        builder.add_node("context_fetch", self.context_fetch)
        builder.add_node("gap_checker", self.gap_checker)
        builder.add_node("tool_planner", self.tool_planner)
        builder.add_node("dispatcher", self.dispatcher)

        # Add edges
        builder.add_edge(START, "task_selector")
        builder.add_conditional_edges(
            "task_selector",
            self._route_after_task_selector,
            {"context_fetch": "context_fetch", "__end__": END},
        )
        builder.add_edge("context_fetch", "gap_checker")
        builder.add_conditional_edges(
            "gap_checker",
            self._route_after_gap_checker,
            {"tool_planner": "tool_planner", "__end__": END},
        )
        builder.add_edge("tool_planner", "dispatcher")
        builder.add_conditional_edges(
            "dispatcher",
            self._route_after_dispatcher,
            {"__end__": END},
        )

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("Orchestrator subgraph compiled")

        return compiled

    # ── Routing Functions ─────────────────────────────────────────────

    @staticmethod
    def _route_after_task_selector(
        state: OrchestratorSubgraphState,
    ) -> Literal["__end__", "context_fetch"]:
        """Route after task selection: end if no tasks, else to context fetch."""
        route_to = state.get("route_to", "context_fetch")
        if route_to == "end":
            return "__end__"
        return "context_fetch"

    @staticmethod
    def _route_after_gap_checker(
        state: OrchestratorSubgraphState,
    ) -> Literal["__end__", "tool_planner"]:
        """Route after gap checking: end if gaps, else to tool_planner."""
        route_to = state.get("route_to", "tool_planner")
        if route_to == "gap_detector":
            return "__end__"  # Parent will route to gap_detector
        return "tool_planner"

    @staticmethod
    def _route_after_dispatcher(state: OrchestratorSubgraphState) -> Literal["__end__"]:
        """Route after dispatch: always end (result contains output)."""
        return "__end__"


# Module-level instance for convenience (no checkpointer by default)
ORCHESTRATOR_SUBGRAPH = OrchestratorSubgraph()


__all__ = ["OrchestratorSubgraph", "ORCHESTRATOR_SUBGRAPH"]
