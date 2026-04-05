"""
ContextSubgraph — context collection + AI review subgraph.

Linear flow: validate_context → collect_context → review → deep_analysis

All nodes extend SubgraphAwareNode with phase="context".
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.nodes.plan_nodes import (
    CollectContextNode,
    DeepAnalysisNode,
    FeedbackReviewNode,
    ReviewNode,
    ValidateContextNode,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import ContextSubgraphState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ContextSubgraph(BaseWorkflowEngine):
    """Context collection + AI review subgraph.

    Extends BaseWorkflowEngine to build a LangGraph StateGraph that handles:
      - Validating user-provided context
      - Collecting context from the codebase
      - AI review of collected context
      - Deep analysis for downstream phases

    Node flow:
        START → validate_context → collect_context → review → deep_analysis → END
    """

    def __init__(self, workflow_context: WorkflowContext) -> None:
        super().__init__(
            workflow_context=workflow_context,
            max_iterations=1,
            workflow_name="context_subgraph",
            use_default_checkpointer=False,
        )

    # ── BaseWorkflowEngine Implementation ─────────────────────────────

    def _initialize_tools(self) -> list:
        """No standalone tools — nodes handle their own tooling."""
        return []

    def _initialize_nodes(self) -> None:
        """Instantiate context subgraph nodes."""
        self.validate_context = ValidateContextNode()
        self.collect_context = CollectContextNode()
        self.review = ReviewNode()
        self.deep_analysis = DeepAnalysisNode()
        self.feedback_review = FeedbackReviewNode()

        logger.info("Context subgraph nodes initialized")

    def _compile_workflow(self) -> CompiledStateGraph:
        """Build and compile the context subgraph as a linear flow."""
        builder = StateGraph(ContextSubgraphState)

        # Add nodes
        builder.add_node("validate_context", self.validate_context)
        builder.add_node("collect_context", self.collect_context)
        builder.add_node("review", self.review)
        builder.add_node("deep_analysis", self.deep_analysis)
        builder.add_node("feedback_review", self.feedback_review)

        # Wire linear flow
        builder.add_edge(START, "validate_context")
        builder.add_edge("validate_context", "collect_context")
        builder.add_edge("collect_context", "review")
        builder.add_edge("review", "deep_analysis")
        builder.add_edge("deep_analysis", "feedback_review")
        builder.add_edge("feedback_review", END)

        compiled = builder.compile(checkpointer=self.checkpointer)

        logger.info("Context subgraph compiled")

        return compiled


__all__ = ["ContextSubgraph"]
