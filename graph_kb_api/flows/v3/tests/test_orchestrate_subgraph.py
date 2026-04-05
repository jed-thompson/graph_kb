"""Tests for OrchestrateSubgraph engine class."""

from unittest.mock import MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.orchestrate_subgraph import (
    OrchestrateSubgraph,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

EXPECTED_NODES = {
    "budget_check",
    "task_selector",
    "fetch_context",
    "gap",
    "tool_plan",
    "dispatch",
    "worker",
    "critique",
    "progress",
}


@pytest.fixture
def mock_context() -> WorkflowContext:
    """Provide a minimal mock WorkflowContext for tests."""
    ctx = MagicMock(spec=WorkflowContext)
    ctx.checkpointer = None
    return ctx


class TestOrchestrateSubgraphCompilation:
    """Test OrchestrateSubgraph initialization and compilation."""

    def test_subgraph_compiles(self, mock_context):
        """OrchestrateSubgraph compiles without errors."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        assert sg.workflow is not None

    def test_all_nine_nodes_present(self, mock_context):
        """All 9 orchestrate nodes are present in the compiled graph."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        node_ids = set(graph.nodes)
        for name in EXPECTED_NODES:
            assert name in node_ids, f"Node '{name}' missing"

    def test_workflow_name(self, mock_context):
        """OrchestrateSubgraph has correct workflow name."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        assert sg.workflow_name == "orchestrate_subgraph"

    def test_tools_empty(self, mock_context):
        """OrchestrateSubgraph has no standalone tools."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        assert sg.tools == []


class TestOrchestrateSubgraphFlow:
    """Test graph flow and edge wiring."""

    def test_start_goes_to_budget_check(self, mock_context):
        """START edge leads to budget_check."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        start_targets = [e.target for e in edges if e.source == "__start__"]
        assert "budget_check" in start_targets

    def test_task_selector_to_fetch_context(self, mock_context):
        """task_selector flows to fetch_context."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "task_selector"]
        assert "fetch_context" in targets

    def test_fetch_context_to_task_context_input(self, mock_context):
        """fetch_context flows to task_context_input."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "fetch_context"]
        assert "task_context_input" in targets

    def test_task_context_input_to_gap(self, mock_context):
        """task_context_input flows to gap."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "task_context_input"]
        assert "gap" in targets

    def test_gap_to_task_research(self, mock_context):
        """gap flows to task_research."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "gap"]
        assert "task_research" in targets

    def test_task_research_to_tool_plan(self, mock_context):
        """task_research flows to tool_plan."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "task_research"]
        assert "tool_plan" in targets

    def test_tool_plan_to_dispatch(self, mock_context):
        """tool_plan flows to dispatch."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "tool_plan"]
        assert "dispatch" in targets

    def test_dispatch_to_worker(self, mock_context):
        """dispatch flows to worker."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "dispatch"]
        assert "worker" in targets

    def test_worker_to_critique(self, mock_context):
        """worker flows to critique."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "worker"]
        assert "critique" in targets

    def test_progress_to_end(self, mock_context):
        """progress flows to END."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges
        targets = [e.target for e in edges if e.source == "progress"]
        assert "__end__" in targets

    def test_linear_flow_task_selector_through_critique(self, mock_context):
        """Verify the full linear chain from task_selector to critique."""
        sg = OrchestrateSubgraph(workflow_context=mock_context)
        graph = sg.workflow.get_graph()
        edges = graph.edges

        expected_chain = [
            ("task_selector", "fetch_context"),
            ("fetch_context", "task_context_input"),
            ("task_context_input", "gap"),
            ("gap", "task_research"),
            ("task_research", "tool_plan"),
            ("tool_plan", "dispatch"),
            ("dispatch", "worker"),
            ("worker", "critique"),
        ]
        edge_set = {(e.source, e.target) for e in edges}
        for src, tgt in expected_chain:
            assert (src, tgt) in edge_set, f"Edge {src} → {tgt} missing"


class TestRouteAfterBudget:
    """Test _route_after_budget conditional routing."""

    def test_budget_ok_routes_to_task_selector(self):
        """When budget has remaining calls, route to task_selector."""
        state = {"budget": {"remaining_llm_calls": 100}}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "task_selector"

    def test_budget_exhausted_routes_to_end(self):
        """When remaining_llm_calls is 0, route to END."""
        state = {"budget": {"remaining_llm_calls": 0}}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "__end__"

    def test_budget_negative_routes_to_end(self):
        """When remaining_llm_calls is negative, route to END."""
        state = {"budget": {"remaining_llm_calls": -5}}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "__end__"

    def test_missing_budget_routes_to_end(self):
        """When budget key is missing, route to END (default 0)."""
        state = {}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "__end__"

    def test_missing_remaining_calls_routes_to_end(self):
        """When remaining_llm_calls key is missing, route to END."""
        state = {"budget": {}}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "__end__"

    def test_budget_one_remaining_routes_to_task_selector(self):
        """When exactly 1 call remaining, route to task_selector."""
        state = {"budget": {"remaining_llm_calls": 1}}
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "task_selector"


class TestRouteAfterCritique:
    """Test _route_after_critique conditional routing."""

    def test_critique_passed_routes_to_progress(self):
        """When critique passed, route to progress."""
        state = {"orchestrate": {"critique_passed": True}}
        result = OrchestrateSubgraph._route_after_critique(state)
        assert result == "progress"

    def test_critique_failed_routes_to_worker(self):
        """When critique failed, route back to worker for retry."""
        state = {"orchestrate": {"critique_passed": False}}
        result = OrchestrateSubgraph._route_after_critique(state)
        assert result == "worker"

    def test_missing_orchestrate_routes_to_progress(self):
        """When orchestrate key is missing, default to progress."""
        state = {}
        result = OrchestrateSubgraph._route_after_critique(state)
        assert result == "progress"

    def test_missing_critique_passed_routes_to_progress(self):
        """When critique_passed key is missing, default to progress."""
        state = {"orchestrate": {}}
        result = OrchestrateSubgraph._route_after_critique(state)
        assert result == "progress"
