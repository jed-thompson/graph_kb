"""
ResearchSubgraph — multi-source research with agent dispatch.

Conditional loop flow:
    formulate_queries → dispatch_research → aggregate → gap_check →
    (confidence_gate | formulate_queries) → approval

All nodes extend SubgraphAwareNode with phase="research".
DispatchResearchNode stores large results via ArtifactService.store()
and returns ArtifactRef in state.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.plan_nodes import (
    AggregateNode,
    ConfidenceGateNode,
    DispatchResearchNode,
    FormulateQueriesNode,
    GapCheckNode,
    ResearchApprovalNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import ResearchSubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ResearchSubgraph(BaseWorkflowEngine):
    """Multi-source research with agent dispatch.

    Extends BaseWorkflowEngine to build a LangGraph StateGraph with a
    conditional loop for iterative research refinement:

        START → formulate_queries → dispatch_research → aggregate →
        gap_check → (confidence_gate | formulate_queries) →
        approval → END

    The conditional edge after gap_check routes back to
    formulate_queries when gaps exist in research coverage,
    or forward to confidence_gate when coverage is sufficient.
    """

    # Maximum iterations for the research loop (Req 0i)
    MAX_RESEARCH_ITERATIONS = 3

    def __init__(self, workflow_context: WorkflowContext) -> None:
        super().__init__(
            workflow_context=workflow_context,
            max_iterations=1,
            workflow_name="research_subgraph",
            use_default_checkpointer=False,
        )

    # ── BaseWorkflowEngine Implementation ─────────────────────────────

    def _initialize_tools(self) -> list:
        """No standalone tools — nodes handle their own tooling."""
        return []

    def _initialize_nodes(self) -> None:
        """Instantiate research subgraph nodes."""
        self.formulate_queries = FormulateQueriesNode()
        self.dispatch_research = DispatchResearchNode()
        self.aggregate = AggregateNode()
        self.gap_check = GapCheckNode()
        self.confidence_gate = ConfidenceGateNode()
        self.approval = ResearchApprovalNode()

        logger.info("Research subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the research subgraph with conditional loop."""
        builder = StateGraph(ResearchSubgraphState)

        # Add nodes
        builder.add_node("formulate_queries", self.formulate_queries)
        builder.add_node("dispatch_research", self.dispatch_research)
        builder.add_node("aggregate", self.aggregate)
        builder.add_node("gap_check", self.gap_check)
        builder.add_node("confidence_gate", self.confidence_gate)
        builder.add_node("approval", self.approval)

        # Wire linear edges
        builder.add_edge(START, "formulate_queries")
        builder.add_edge("formulate_queries", "dispatch_research")
        builder.add_edge("dispatch_research", "aggregate")
        builder.add_edge("aggregate", "gap_check")

        # Conditional loop: gap_check → formulate_queries or confidence_gate
        builder.add_conditional_edges(
            "gap_check",
            ResearchSubgraph._route_after_gap_check,
            {
                "formulate_queries": "formulate_queries",
                "confidence_gate": "confidence_gate",
            },
        )

        # Continue to approval
        builder.add_edge("confidence_gate", "approval")

        # Conditional routing after approval: approve→END, request_more→loop, reject→END
        builder.add_conditional_edges(
            "approval",
            ResearchSubgraph._route_after_approval,
            {
                "formulate_queries": "formulate_queries",
                "__end__": END,
            },
        )

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("Research subgraph compiled")

        return compiled

    @staticmethod
    def _route_after_gap_check(
        state: dict,
    ) -> Literal["formulate_queries", "confidence_gate"]:
        """Route after gap_check based on research gaps.

        If gaps exist in research coverage, loop back to
        formulate_queries for another iteration. Otherwise,
        proceed to confidence_gate.

        Includes loop guard to prevent infinite research iterations.
        After MAX_RESEARCH_ITERATIONS, forces confidence_gate regardless
        of gaps.

        Args:
            state: Current workflow state.

        Returns:
            "formulate_queries" if gaps exist, "confidence_gate" otherwise.
        """
        research = state.get("research", {})
        gaps = research.get("gaps", [])
        structured_data_available = research.get("structured_data_available", True)

        if gaps:
            iteration_count = research.get("research_gap_iterations", 0)
            if iteration_count >= ResearchSubgraph.MAX_RESEARCH_ITERATIONS:
                # Loop guard: force confidence_gate after max iterations
                return "confidence_gate"
            # Break loop early when research can't retrieve structured data AND
            # we've already attempted at least 2 iterations — additional iterations
            # won't produce different results.
            if not structured_data_available and iteration_count >= 2:
                logger.info(
                    "[research] Breaking loop: no structured data available "
                    f"after {iteration_count} iteration(s). Proceeding to confidence_gate."
                )
                return "confidence_gate"
            return "formulate_queries"
        return "confidence_gate"

    @staticmethod
    def _route_after_approval(
        state: dict,
    ) -> Literal["formulate_queries", "__end__"]:
        """Route after research approval based on user decision.

        - approve: proceed to next phase (END)
        - request_more: loop back to formulate_queries for more research
        - reject: halt workflow (END, workflow_status set by node)
        """
        decision = state.get("research", {}).get("approval_decision", "approve")
        if decision == "request_more":
            return "formulate_queries"
        return "__end__"


__all__ = ["ResearchSubgraph"]
