"""Tests for PlanningSubgraph engine class."""

from unittest.mock import MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.planning_subgraph import (
    PlanningSubgraph,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

EXPECTED_NODES = {
    "roadmap",
    "feasibility",
    "decompose",
    "validate_dag",
    "assign",
    "align",
    "approval",
}


@pytest.fixture
def mock_context() -> WorkflowContext:
    """Provide a minimal mock WorkflowContext for tests."""
    ctx = MagicMock(spec=WorkflowContext)
    ctx.checkpointer = None
    return ctx


LINEAR_FLOW = [
    ("__start__", "roadmap"),
    ("roadmap", "feasibility"),
    ("feasibility", "decompose"),
    ("decompose", "validate_dag"),
    ("validate_dag", "assign"),
    ("assign", "align"),
    ("align", "approval"),
    ("approval", "__end__"),
]


class TestPlanningSubgraphCompilation:
    """Test PlanningSubgraph initialization and compilation."""

    def test_subgraph_compiles(self, mock_context):
        """PlanningSubgraph compiles without errors."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        assert sg.workflow is not None

    def test_all_seven_nodes_present(self, mock_context):
        """All 7 planning nodes are present in the compiled graph."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        node_ids = set(graph.nodes)
        for name in EXPECTED_NODES:
            assert name in node_ids, f"Node '{name}' missing"

    def test_workflow_name(self, mock_context):
        """PlanningSubgraph has correct workflow name."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        assert sg.workflow_name == "planning_subgraph"

    def test_tools_empty(self, mock_context):
        """PlanningSubgraph has no standalone tools."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        assert sg.tools == []


class TestPlanningSubgraphFlow:
    """Test graph flow and edge wiring — linear flow from START to END."""

    def test_linear_flow(self, mock_context):
        """Full linear flow: START through approval to END."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges

        for source, target in LINEAR_FLOW:
            targets = [e.target for e in edges if e.source == source]
            assert target in targets, f"Expected edge {source} → {target}, but {source} targets are {targets}"

    def test_start_goes_to_roadmap(self, mock_context):
        """START edge leads to roadmap."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        start_targets = [e.target for e in edges if e.source == "__start__"]
        assert "roadmap" in start_targets

    def test_approval_to_end(self, mock_context):
        """approval flows to END."""
        sg = PlanningSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        approval_targets = [e.target for e in edges if e.source == "approval"]
        assert "__end__" in approval_targets
