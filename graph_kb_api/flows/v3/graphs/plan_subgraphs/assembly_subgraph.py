"""AssemblySubgraph -- completeness + composition review + generation + consistency check + final assembly.

Conditional routing flow:
    START -> completeness -> composition_review -> template -> generate -> consistency ->
    (generate | assemble) -> validate -> approval -> END

All nodes extend SubgraphAwareNode with phase="assembly".
GenerateNode stores sections via ArtifactService.store().
AssembleNode stores final document via ArtifactService.store() at output/spec.md.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.plan_subgraphs.plan_subgraph_base import PlanSubgraph
from graph_kb_api.flows.v3.nodes.plan.assembly_nodes import (
    AssembleNode,
    AssemblyApprovalNode,
    CompletenessNode,
    CompositionReviewNode,
    ConsistencyNode,
    GenerateNode,
    TemplateNode,
    ValidateNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import AssemblySubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class AssemblySubgraph(PlanSubgraph):
    """Completeness + composition review + generation + consistency check + final assembly.

    Extends PlanSubgraph to build a LangGraph StateGraph with
    conditional routing for consistency-driven regeneration:

        START → completeness → composition_review → template → generate → consistency →
        (generate | assemble) → validate → approval → END

    The conditional edge after consistency routes back to generate
    when consistency issues exist, or forward to assemble when
    content is consistent.
    """

    # Maximum iterations for the consistency loop (Req 0i)
    MAX_CONSISTENCY_ITERATIONS = 3

    def __init__(self, workflow_context: WorkflowContext) -> None:
        super().__init__(workflow_context, "assembly_subgraph")

    def _initialize_nodes(self) -> None:
        """Instantiate assembly subgraph nodes."""
        self.completeness = CompletenessNode()
        self.composition_review = CompositionReviewNode()
        self.template = TemplateNode()
        self.generate = GenerateNode()
        self.consistency = ConsistencyNode()
        self.assemble = AssembleNode()
        self.validate = ValidateNode()
        self.approval = AssemblyApprovalNode()

        logger.info("Assembly subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the assembly subgraph with conditional routing."""
        builder = StateGraph(AssemblySubgraphState)

        # Add nodes
        builder.add_node("completeness", self.completeness)
        builder.add_node("composition_review", self.composition_review)
        builder.add_node("template", self.template)
        builder.add_node("generate", self.generate)
        builder.add_node("consistency", self.consistency)
        builder.add_node("assemble", self.assemble)
        builder.add_node("validate", self.validate)
        builder.add_node("approval", self.approval)

        # Wire linear edges
        builder.add_edge(START, "completeness")
        builder.add_edge("completeness", "composition_review")
        builder.add_edge("composition_review", "template")
        builder.add_edge("template", "generate")
        builder.add_edge("generate", "consistency")

        # Conditional routing: consistency → generate (retry) or assemble
        builder.add_conditional_edges(
            "consistency",
            AssemblySubgraph._route_after_consistency,
            {
                "generate": "generate",
                "assemble": "assemble",
            },
        )

        # Continue to validate and approval
        builder.add_edge("assemble", "validate")
        builder.add_edge("validate", "approval")

        # Conditional routing after approval: approve→END, revise→generate, reject→END
        builder.add_conditional_edges(
            "approval",
            AssemblySubgraph._route_after_approval,
            {
                "generate": "generate",
                "__end__": END,
            },
        )

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("Assembly subgraph compiled")

        return compiled

    @staticmethod
    def _route_after_consistency(
        state: dict,
    ) -> Literal["generate", "assemble"]:
        """Route after consistency check based on issues found.

        If consistency issues exist, loop back to generate for
        another iteration. Otherwise, proceed to assemble.

        Includes loop guard to prevent infinite consistency iterations.
        After MAX_CONSISTENCY_ITERATIONS, forces assemble regardless of
        issues.

        Args:
            state: Current workflow state.

        Returns:
            "generate" if consistency issues exist, "assemble" otherwise.
        """
        issues = state.get("completeness", {}).get("consistency_issues", [])
        if issues:
            iteration_count = state.get("completeness", {}).get("consistency_iterations", 0)
            if iteration_count >= AssemblySubgraph.MAX_CONSISTENCY_ITERATIONS:
                # Loop guard: force assemble after max iterations
                return "assemble"
            return "generate"
        return "assemble"

    @staticmethod
    def _route_after_approval(
        state: dict,
    ) -> Literal["generate", "__end__"]:
        """Route after assembly approval based on user decision.

        - approve: proceed to next phase (END)
        - revise: loop back to generate for revised assembly
        - reject: halt workflow (END, workflow_status set by node)
        """
        decision = state.get("completeness", {}).get("approval_decision", "approve")
        if decision == "revise":
            return "generate"
        return "__end__"


__all__ = ["AssemblySubgraph"]
