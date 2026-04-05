"""Tests for AssemblySubgraph engine class."""

from unittest.mock import MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.assembly_subgraph import (
    AssemblySubgraph,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

EXPECTED_NODES = {
    "completeness",
    "composition_review",
    "template",
    "generate",
    "consistency",
    "assemble",
    "validate",
    "approval",
}


@pytest.fixture
def mock_context() -> WorkflowContext:
    """Provide a minimal mock WorkflowContext for tests."""
    ctx = MagicMock(spec=WorkflowContext)
    ctx.checkpointer = None
    return ctx


class TestAssemblySubgraphCompilation:
    """Test AssemblySubgraph initialization and compilation."""

    def test_subgraph_compiles(self, mock_context):
        """AssemblySubgraph compiles without errors."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        assert sg.workflow is not None

    def test_all_seven_nodes_present(self, mock_context):
        """All 7 assembly nodes are present in the compiled graph."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        node_ids = set(graph.nodes)
        for name in EXPECTED_NODES:
            assert name in node_ids, f"Node '{name}' missing"

    def test_workflow_name(self, mock_context):
        """AssemblySubgraph has correct workflow name."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        assert sg.workflow_name == "assembly_subgraph"

    def test_tools_empty(self, mock_context):
        """AssemblySubgraph has no standalone tools."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        assert sg.tools == []


class TestAssemblySubgraphFlow:
    """Test graph flow and edge wiring."""

    def test_start_goes_to_completeness(self, mock_context):
        """START edge leads to completeness."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        start_targets = [e.target for e in edges if e.source == "__start__"]
        assert "completeness" in start_targets

    def test_completeness_to_composition_review(self, mock_context):
        """completeness flows to composition_review."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "completeness"]
        assert "composition_review" in targets

    def test_composition_review_to_template(self, mock_context):
        """composition_review flows to template."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "composition_review"]
        assert "template" in targets

    def test_template_to_generate(self, mock_context):
        """template flows to generate."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "template"]
        assert "generate" in targets

    def test_generate_to_consistency(self, mock_context):
        """generate flows to consistency."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "generate"]
        assert "consistency" in targets

    def test_linear_flow_completeness_through_consistency(self, mock_context):
        """Verify the linear chain from completeness to consistency."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges

        expected_chain = [
            ("completeness", "composition_review"),
            ("composition_review", "template"),
            ("template", "generate"),
            ("generate", "consistency"),
        ]
        edge_set = {(e.source, e.target) for e in edges}
        for src, tgt in expected_chain:
            assert (src, tgt) in edge_set, f"Edge {src} → {tgt} missing"

    def test_assemble_to_validate(self, mock_context):
        """assemble flows to validate."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "assemble"]
        assert "validate" in targets

    def test_validate_to_approval(self, mock_context):
        """validate flows to approval."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "validate"]
        assert "approval" in targets

    def test_approval_to_end(self, mock_context):
        """approval flows to END."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "approval"]
        assert "__end__" in targets

    def test_linear_flow_assemble_through_end(self, mock_context):
        """Verify the linear chain from assemble to END."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges

        expected_chain = [
            ("assemble", "validate"),
            ("validate", "approval"),
            ("approval", "__end__"),
        ]
        edge_set = {(e.source, e.target) for e in edges}
        for src, tgt in expected_chain:
            assert (src, tgt) in edge_set, f"Edge {src} → {tgt} missing"


class TestRouteAfterConsistency:
    """Test _route_after_consistency conditional routing."""

    def test_with_issues_routes_to_generate(self):
        """When consistency issues exist, route back to generate."""
        state = {"completeness": {"consistency_issues": [{"issue": "mismatch"}]}}
        result = AssemblySubgraph._route_after_consistency(state)
        assert result == "generate"

    def test_without_issues_routes_to_assemble(self):
        """When no consistency issues, route to assemble."""
        state = {"completeness": {"consistency_issues": []}}
        result = AssemblySubgraph._route_after_consistency(state)
        assert result == "assemble"

    def test_missing_completeness_key_routes_to_assemble(self):
        """When completeness key is missing, route to assemble."""
        state = {}
        result = AssemblySubgraph._route_after_consistency(state)
        assert result == "assemble"

    def test_missing_consistency_issues_key_routes_to_assemble(self):
        """When consistency_issues key is missing, route to assemble."""
        state = {"completeness": {}}
        result = AssemblySubgraph._route_after_consistency(state)
        assert result == "assemble"

    def test_multiple_issues_routes_to_generate(self):
        """Multiple consistency issues still route to generate."""
        state = {
            "completeness": {
                "consistency_issues": [
                    {"issue": "a"},
                    {"issue": "b"},
                    {"issue": "c"},
                ]
            }
        }
        result = AssemblySubgraph._route_after_consistency(state)
        assert result == "generate"

    def test_conditional_edge_targets_in_graph(self, mock_context):
        """Consistency node has conditional edges to both generate and assemble."""
        sg = AssemblySubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = {e.target for e in edges if e.source == "consistency"}
        assert "generate" in targets, "Missing conditional edge to generate"
        assert "assemble" in targets, "Missing conditional edge to assemble"
