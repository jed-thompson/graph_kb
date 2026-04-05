"""Tests for ResearchSubgraph engine class."""

from unittest.mock import MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.research_subgraph import (
    ResearchSubgraph,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

EXPECTED_NODES = {
    "formulate_queries",
    "dispatch_research",
    "aggregate",
    "gap_check",
    "confidence_gate",
    "approval",
}


@pytest.fixture
def mock_context() -> WorkflowContext:
    """Provide a minimal mock WorkflowContext for tests."""
    ctx = MagicMock(spec=WorkflowContext)
    ctx.checkpointer = None
    return ctx


class TestResearchSubgraphCompilation:
    """Test ResearchSubgraph initialization and compilation."""

    def test_subgraph_compiles(self, mock_context):
        """ResearchSubgraph compiles without errors."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        assert sg.workflow is not None

    def test_all_six_nodes_present(self, mock_context):
        """All 6 research nodes are present in the compiled graph."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        node_ids = set(graph.nodes)
        for name in EXPECTED_NODES:
            assert name in node_ids, f"Node '{name}' missing"

    def test_workflow_name(self, mock_context):
        """ResearchSubgraph has correct workflow name."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        assert sg.workflow_name == "research_subgraph"

    def test_tools_empty(self, mock_context):
        """ResearchSubgraph has no standalone tools."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        assert sg.tools == []


class TestResearchSubgraphFlow:
    """Test graph flow and edge wiring."""

    def test_start_goes_to_formulate_queries(self, mock_context):
        """START edge leads to formulate_queries."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        graph.nodes["__start__"]
        # __start__ should have an edge to formulate_queries
        edges = graph.edges
        start_targets = [e.target for e in edges if e.source == "__start__"]
        assert "formulate_queries" in start_targets

    def test_confidence_gate_to_approval(self, mock_context):
        """confidence_gate flows to approval."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        cg_targets = [e.target for e in edges if e.source == "confidence_gate"]
        assert "approval" in cg_targets

    def test_approval_to_end(self, mock_context):
        """approval flows to END."""
        sg = ResearchSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        approval_targets = [e.target for e in edges if e.source == "approval"]
        assert "__end__" in approval_targets


class TestRouteAfterGapCheck:
    """Test _route_after_gap_check conditional routing."""

    def test_with_gaps_routes_to_formulate_queries(self):
        """When gaps exist, route back to formulate_queries."""
        state = {"research": {"gaps": ["missing topic A"]}}
        result = ResearchSubgraph._route_after_gap_check(state)
        assert result == "formulate_queries"

    def test_without_gaps_routes_to_confidence_gate(self):
        """When no gaps, route to confidence_gate."""
        state = {"research": {"gaps": []}}
        result = ResearchSubgraph._route_after_gap_check(state)
        assert result == "confidence_gate"

    def test_missing_research_key_routes_to_confidence_gate(self):
        """When research key is missing, route to confidence_gate."""
        state = {}
        result = ResearchSubgraph._route_after_gap_check(state)
        assert result == "confidence_gate"

    def test_missing_gaps_key_routes_to_confidence_gate(self):
        """When gaps key is missing, route to confidence_gate."""
        state = {"research": {}}
        result = ResearchSubgraph._route_after_gap_check(state)
        assert result == "confidence_gate"

    def test_multiple_gaps_routes_to_formulate_queries(self):
        """Multiple gaps still route to formulate_queries."""
        state = {"research": {"gaps": ["gap1", "gap2", "gap3"]}}
        result = ResearchSubgraph._route_after_gap_check(state)
        assert result == "formulate_queries"
