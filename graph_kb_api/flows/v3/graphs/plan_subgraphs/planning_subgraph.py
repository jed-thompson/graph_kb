"""
PlanningSubgraph — roadmap + decompose + agent/tool assignment.

Linear flow:
    roadmap → feasibility → decompose → validate_dag →
    assign → align → approval

All nodes extend SubgraphAwareNode with phase="planning".
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.plan_subgraphs.plan_subgraph_base import PlanSubgraph
from graph_kb_api.flows.v3.nodes.plan.planning_nodes import (
    AlignNode,
    AssignNode,
    DecomposeNode,
    FeasibilityNode,
    PlanningApprovalNode,
    RoadmapNode,
    ValidateDagNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import PlanningSubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class PlanningSubgraph(PlanSubgraph):
    """Roadmap + decompose + agent/tool assignment.

    Extends PlanSubgraph to build a LangGraph StateGraph that handles:
      - Generating a high-level roadmap
      - Assessing feasibility
      - Decomposing into a task DAG
      - Validating the DAG structure
      - Assigning agents and tools to tasks
      - Aligning plan with requirements
      - Approval gate for planning phase

    Node flow:
        START → roadmap → feasibility → decompose →
        validate_dag → assign → align → approval → END
    """

    def __init__(self, workflow_context: WorkflowContext) -> None:
        super().__init__(workflow_context, "planning_subgraph")

    def _initialize_nodes(self) -> None:
        """Instantiate planning subgraph nodes."""
        self.roadmap = RoadmapNode()
        self.feasibility = FeasibilityNode()
        self.decompose = DecomposeNode()
        self.validate_dag = ValidateDagNode()
        self.assign = AssignNode()
        self.align = AlignNode()
        self.approval = PlanningApprovalNode()

        logger.info("Planning subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the planning subgraph as a linear flow."""
        builder = StateGraph(PlanningSubgraphState)

        # Add nodes
        builder.add_node("roadmap", self.roadmap)
        builder.add_node("feasibility", self.feasibility)
        builder.add_node("decompose", self.decompose)
        builder.add_node("validate_dag", self.validate_dag)
        builder.add_node("assign", self.assign)
        builder.add_node("align", self.align)
        builder.add_node("approval", self.approval)

        # Wire linear flow
        builder.add_edge(START, "roadmap")
        builder.add_edge("roadmap", "feasibility")
        builder.add_edge("feasibility", "decompose")
        builder.add_edge("decompose", "validate_dag")
        builder.add_edge("validate_dag", "assign")
        builder.add_edge("assign", "align")
        builder.add_edge("align", "approval")

        # Conditional routing after approval: approve→END, revise→roadmap, reject→END
        builder.add_conditional_edges(
            "approval",
            PlanningSubgraph._route_after_approval,
            {
                "roadmap": "roadmap",
                "__end__": END,
            },
        )

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("Planning subgraph compiled")

        return compiled

    @staticmethod
    def _route_after_approval(
        state: dict,
    ) -> Literal["roadmap", "__end__"]:
        """Route after planning approval based on user decision.

        - approve: proceed to next phase (END)
        - revise: loop back to roadmap for revised planning
        - reject: halt workflow (END, workflow_status set by node)
        """
        decision = state.get("plan", {}).get("approval_decision", "approve")
        if decision == "revise":
            return "roadmap"
        return "__end__"


__all__ = ["PlanningSubgraph"]
