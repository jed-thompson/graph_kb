"""Tests for budget exhaustion graceful completion (Task 13.1).

Validates Requirements 28.1, 28.2, 28.3:
- On BudgetExhaustedError, emit progress event with budget exhaustion message
- Transition to graceful completion preserving all artifacts and state
- Allow user to increase budget limits and resume from paused phase
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.orchestrate_subgraph import (
    OrchestrateSubgraph,
)
from graph_kb_api.flows.v3.models.node_models import (
    NodeExecutionResult,
    NodeExecutionStatus,
)
from graph_kb_api.flows.v3.nodes.plan_nodes import BudgetCheckNode
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.services.budget_guard import BudgetExhaustedError
from graph_kb_api.websocket.plan_events import PlanResumePayload


@pytest.fixture(autouse=True)
def mock_langgraph_interrupt():
    """Mock LangGraph's interrupt() to prevent runtime errors in direct _execute_async tests."""
    with patch("graph_kb_api.flows.v3.nodes.subgraph_aware_node.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"decision": "accept_results"}
        yield mock_interrupt


def _make_budget(
    remaining: int = 200,
    tokens_used: int = 0,
    max_tokens: int = 500_000,
    max_wall_clock_s: int = 1800,
):
    """Create a BudgetState dict for testing."""
    return {
        "max_llm_calls": 200,
        "remaining_llm_calls": remaining,
        "max_tokens": max_tokens,
        "tokens_used": tokens_used,
        "max_wall_clock_s": max_wall_clock_s,
        "started_at": datetime.now(UTC).isoformat(),
    }


# ── BudgetCheckNode Tests ────────────────────────────────────────


class TestBudgetCheckNodeExhaustion:
    """Test BudgetCheckNode handles budget exhaustion gracefully."""

    @pytest.mark.asyncio
    async def test_budget_ok_returns_empty_output(self):
        """When budget has capacity, BudgetCheckNode returns empty output."""
        node = BudgetCheckNode()
        state = {"budget": _make_budget(remaining=100), "session_id": "s1", "document_manifest": {}}
        config = {"configurable": {}}
        result = await node._execute_async(state, config)
        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output.get("workflow_status") is None

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_budget_exhausted_status(self):
        """When budget is exhausted, returns workflow_status=budget_exhausted."""
        node = BudgetCheckNode()
        state = {"budget": _make_budget(remaining=0), "session_id": "s1"}
        config = {"configurable": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_budget_warning",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "orchestrate"

    @pytest.mark.asyncio
    async def test_budget_exhausted_sets_error_info(self):
        """When budget is exhausted, error dict contains code and phase."""
        node = BudgetCheckNode()
        state = {"budget": _make_budget(remaining=0), "session_id": "s1"}
        config = {"configurable": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_budget_warning",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, config)

        error = result.output["error"]
        assert error["code"] == "BUDGET_EXHAUSTED"
        assert error["phase"] == "orchestrate"
        assert "Budget exhausted" in error["message"]

    @pytest.mark.asyncio
    async def test_budget_exhausted_emits_warning(self):
        """When budget is exhausted, emit_budget_warning is called."""
        node = BudgetCheckNode()
        state = {"budget": _make_budget(remaining=0), "session_id": "s1"}
        config = {"configurable": {"client_id": "c1"}}
        node._config = config

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_budget_warning",
            new_callable=AsyncMock,
        ) as mock_warn:
            await node._execute_async(state, config)

        mock_warn.assert_awaited_once()
        call_kwargs = mock_warn.call_args
        assert call_kwargs.kwargs["session_id"] == "s1"
        assert call_kwargs.kwargs["client_id"] == "c1"

    @pytest.mark.asyncio
    async def test_budget_exhausted_tokens(self):
        """Token limit exhaustion triggers budget_exhausted status."""
        node = BudgetCheckNode()
        state = {
            "budget": _make_budget(remaining=100, tokens_used=500_000, max_tokens=500_000),
            "session_id": "s1",
        }
        config = {"configurable": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_budget_warning",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, config)

        assert result.output["workflow_status"] == "budget_exhausted"


# ── SubgraphAwareNode BudgetExhaustedError Catch Tests ───────────


class _RaisingNode(SubgraphAwareNode):
    """Test node that raises BudgetExhaustedError in _execute_step."""

    def __init__(self):
        super().__init__(node_name="raising_node")
        self.phase = "research"
        self.step_name = "raising_step"
        self.step_progress = 0.5

    async def _execute_step(self, state, config):
        raise BudgetExhaustedError("LLM call limit reached")


class _NormalNode(SubgraphAwareNode):
    """Test node that returns normally."""

    def __init__(self):
        super().__init__(node_name="normal_node")
        self.phase = "context"
        self.step_name = "normal_step"
        self.step_progress = 0.3

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output={"key": "value"})


class TestSubgraphAwareNodeBudgetCatch:
    """Test SubgraphAwareNode catches BudgetExhaustedError in _execute_async."""

    @pytest.mark.asyncio
    async def test_catches_budget_exhausted_error(self):
        """BudgetExhaustedError is caught and returns graceful completion."""
        node = _RaisingNode()
        node._config = {"configurable": {}}
        state = {"session_id": "s1", "budget": _make_budget()}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, None)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "research"

    @pytest.mark.asyncio
    async def test_emits_progress_on_budget_exhaustion(self):
        """Progress callback is called with budget exhaustion message."""
        node = _RaisingNode()
        progress_cb = AsyncMock()
        node._config = {"configurable": {"progress_callback": progress_cb}}
        state = {"session_id": "s1", "budget": _make_budget()}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            await node._execute_async(state, None)

        # Should be called twice: once on entry, once on budget exhaustion
        assert progress_cb.await_count == 2
        exhaustion_call = progress_cb.call_args_list[1][0][0]
        assert "Budget exhausted" in exhaustion_call["message"]
        assert exhaustion_call["phase"] == "research"

    @pytest.mark.asyncio
    async def test_normal_execution_unaffected(self):
        """Normal node execution still works with transition log appended."""
        node = _NormalNode()
        node._config = {"configurable": {}}
        state = {"session_id": "s1", "budget": _make_budget()}

        result = await node._execute_async(state, None)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["key"] == "value"
        assert "transition_log" in result.output
        assert len(result.output["transition_log"]) == 1

    @pytest.mark.asyncio
    async def test_budget_exhaustion_preserves_artifacts(self):
        """Budget exhaustion does not clear existing artifacts from state."""
        node = _RaisingNode()
        node._config = {"configurable": {}}
        state = {
            "session_id": "s1",
            "budget": _make_budget(),
            "artifacts": {
                "research.findings": {
                    "key": "k",
                    "content_hash": "h",
                    "summary": "Findings summary",
                    "size_bytes": 100,
                    "created_at": "2024-06-01T12:00:00Z",
                }
            },
        }

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, None)

        # The result output should NOT clear artifacts — it only sets status fields
        assert "artifacts" not in result.output
        assert result.output["workflow_status"] == "budget_exhausted"


# ── Route After Budget Tests (with budget_exhausted status) ──────


class TestRouteAfterBudgetWithStatus:
    """Test _route_after_budget handles budget_exhausted workflow_status."""

    def test_budget_exhausted_status_routes_to_end(self):
        """When workflow_status is budget_exhausted, route to END."""
        state = {
            "workflow_status": "budget_exhausted",
            "budget": {"remaining_llm_calls": 100},
        }
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "__end__"

    def test_running_status_with_budget_routes_to_task_selector(self):
        """When workflow_status is running and budget OK, route to task_selector."""
        state = {
            "workflow_status": "running",
            "budget": {"remaining_llm_calls": 100},
        }
        result = OrchestrateSubgraph._route_after_budget(state)
        assert result == "task_selector"


# ── PlanResumePayload Tests ──────────────────────────────────────


class TestPlanResumePayloadBudgetFields:
    """Test PlanResumePayload accepts optional budget override fields."""

    def test_basic_resume_payload(self):
        """Basic resume payload with just session_id."""
        payload = PlanResumePayload(session_id="s1")
        assert payload.session_id == "s1"
        assert payload.max_llm_calls is None
        assert payload.max_tokens is None
        assert payload.max_wall_clock_s is None

    def test_resume_with_budget_overrides(self):
        """Resume payload with budget limit overrides."""
        payload = PlanResumePayload(
            session_id="s1",
            max_llm_calls=400,
            max_tokens=1_000_000,
            max_wall_clock_s=3600,
        )
        assert payload.max_llm_calls == 400
        assert payload.max_tokens == 1_000_000
        assert payload.max_wall_clock_s == 3600

    def test_resume_with_partial_overrides(self):
        """Resume payload with only some budget fields."""
        payload = PlanResumePayload(session_id="s1", max_llm_calls=500)
        assert payload.max_llm_calls == 500
        assert payload.max_tokens is None
