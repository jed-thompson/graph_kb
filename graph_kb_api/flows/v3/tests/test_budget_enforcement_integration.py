"""Integration tests: Budget enforcement — run nodes until budget exhausted, verify graceful stop.

Simulates a sequence of nodes that decrement budget, then hit exhaustion.
Verifies BudgetCheckNode returns budget_exhausted status, SubgraphAwareNode
catches BudgetExhaustedError and returns graceful completion, artifacts
produced before exhaustion are preserved, and budget monotonicity holds.

**Validates: Requirements 7.1, 28.1, 28.2**
"""

from datetime import UTC, datetime
from typing import Any, Dict, Generator
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
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.state.plan_state import ArtifactRef


@pytest.fixture(autouse=True)
def mock_langgraph_interrupt() -> Generator[AsyncMock, None, None]:
    """Mock LangGraph's interrupt() to prevent runtime errors in direct _execute_async tests."""
    with patch("graph_kb_api.flows.v3.nodes.subgraph_aware_node.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"decision": "accept_results"}
        yield mock_interrupt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_budget(
    remaining: int = 200,
    tokens_used: int = 0,
    max_tokens: int = 500_000,
    max_wall_clock_s: int = 1800,
) -> Dict[str, Any]:
    return {
        "max_llm_calls": 200,
        "remaining_llm_calls": remaining,
        "max_tokens": max_tokens,
        "tokens_used": tokens_used,
        "max_wall_clock_s": max_wall_clock_s,
        "started_at": datetime.now(UTC).isoformat(),
    }


def _make_artifact_ref(namespace: str, name: str) -> ArtifactRef:
    return ArtifactRef(
        key=f"specs/test-session/{namespace}/{name}",
        content_hash="a1b2c3d4e5f6" + "0" * 52,
        size_bytes=4096,
        created_at="2024-06-01T12:00:00Z",
        summary=f"Summary for {namespace}/{name}.",
    )


# ---------------------------------------------------------------------------
# Test nodes that simulate LLM work
# ---------------------------------------------------------------------------


class _LLMWorkNode(SubgraphAwareNode[Dict[str, Any]]):
    """Simulates a node that does LLM work and decrements budget."""

    def __init__(self, calls_per_step: int = 1, tokens_per_step: int = 500) -> None:
        super().__init__(node_name="llm_work")
        self.phase = "orchestrate"
        self.step_name = "llm_work"
        self.step_progress = 0.5
        self.calls_per_step = calls_per_step
        self.tokens_per_step = tokens_per_step

    async def _execute_step(self, state: Dict[str, Any], config: Dict[str, Any]) -> NodeExecutionResult:
        budget = state["budget"]
        BudgetGuard.check(budget)
        new_budget = BudgetGuard.decrement(
            budget, llm_calls=self.calls_per_step, tokens_used=self.tokens_per_step
        )
        return NodeExecutionResult.success(output={"budget": new_budget})


class _ArtifactProducingNode(SubgraphAwareNode[Dict[str, Any]]):
    """Simulates a node that produces an artifact and decrements budget."""

    def __init__(self, artifact_key: str) -> None:
        super().__init__(node_name="artifact_producer")
        self.phase = "orchestrate"
        self.step_name = "artifact_producer"
        self.step_progress = 0.3
        self.artifact_key = artifact_key

    async def _execute_step(self, state: Dict[str, Any], config: Dict[str, Any]) -> NodeExecutionResult:
        budget = state["budget"]
        BudgetGuard.check(budget)
        new_budget = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=1000)
        new_artifact = _make_artifact_ref("orchestrate", self.artifact_key)
        return NodeExecutionResult.success(
            output={
                "budget": new_budget,
                "artifacts": {self.artifact_key: new_artifact},
            }
        )


# ---------------------------------------------------------------------------
# Test: BudgetCheckNode returns budget_exhausted when budget is 0
# ---------------------------------------------------------------------------


class TestBudgetCheckNodeEnforcement:
    """Verify BudgetCheckNode returns budget_exhausted status when budget is 0."""

    @pytest.mark.asyncio
    async def test_budget_zero_returns_exhausted_status(self) -> None:
        """Req 7.1: remaining_llm_calls <= 0 triggers BudgetExhaustedError path."""
        node = BudgetCheckNode()
        state: Dict[str, Any] = {"budget": _make_budget(remaining=0), "session_id": "s1"}
        config: Dict[str, Any] = {"configurable": {}}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_budget_warning",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "orchestrate"
        assert result.output["error"]["code"] == "BUDGET_EXHAUSTED"

    @pytest.mark.asyncio
    async def test_budget_positive_returns_empty(self) -> None:
        """When budget has capacity, BudgetCheckNode returns empty output."""
        node = BudgetCheckNode()
        state: Dict[str, Any] = {"budget": _make_budget(remaining=10), "session_id": "s1", "document_manifest": {}}
        config: Dict[str, Any] = {"configurable": {}}

        result = await node._execute_step(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output == {}

    @pytest.mark.asyncio
    async def test_token_limit_triggers_exhaustion(self) -> None:
        """Req 7.1: tokens_used >= max_tokens triggers exhaustion."""
        node = BudgetCheckNode()
        state: Dict[str, Any] = {
            "budget": _make_budget(
                remaining=100, tokens_used=500_000, max_tokens=500_000
            ),
            "session_id": "s1",
        }
        config: Dict[str, Any] = {"configurable": {}}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_budget_warning",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, config)

        assert result.output["workflow_status"] == "budget_exhausted"


# ---------------------------------------------------------------------------
# Test: SubgraphAwareNode catches BudgetExhaustedError gracefully
# ---------------------------------------------------------------------------


class TestSubgraphAwareNodeBudgetCatch:
    """Verify SubgraphAwareNode catches BudgetExhaustedError from any node."""

    @pytest.mark.asyncio
    async def test_catches_error_returns_graceful_completion(self) -> None:
        """Req 28.1: On BudgetExhaustedError, transition to graceful completion."""
        node = _LLMWorkNode(calls_per_step=1, tokens_per_step=500)
        node._config = {"configurable": {}}
        state: Dict[str, Any] = {"session_id": "s1", "budget": _make_budget(remaining=0)}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "orchestrate"

    @pytest.mark.asyncio
    async def test_emits_progress_event_on_exhaustion(self) -> None:
        """Req 28.1: Emit progress event with budget exhaustion message."""
        node = _LLMWorkNode()
        progress_cb = AsyncMock()
        node._config = {"configurable": {"progress_callback": progress_cb}}
        state: Dict[str, Any] = {"session_id": "s1", "budget": _make_budget(remaining=0)}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            await node._execute_async(state, {})

        assert progress_cb.await_count == 2
        exhaustion_call = progress_cb.call_args_list[1][0][0]
        assert "Budget exhausted" in exhaustion_call["message"]

    @pytest.mark.asyncio
    async def test_error_dict_has_correct_fields(self) -> None:
        """Req 28.1: Error dict contains code=BUDGET_EXHAUSTED and phase."""
        node = _LLMWorkNode()
        node._config = {"configurable": {}}
        state: Dict[str, Any] = {"session_id": "s1", "budget": _make_budget(remaining=0)}

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, {})

        error = result.output["error"]
        assert error["code"] == "BUDGET_EXHAUSTED"
        assert error["phase"] == "orchestrate"
        assert "Budget exhausted" in error["message"]


# ---------------------------------------------------------------------------
# Test: Artifacts produced before exhaustion are preserved
# ---------------------------------------------------------------------------


class TestArtifactPreservationOnExhaustion:
    """Verify artifacts produced before budget exhaustion are preserved in state."""

    @pytest.mark.asyncio
    async def test_pre_exhaustion_artifacts_not_cleared(self) -> None:
        """Req 28.2: Preserve all artifacts and state produced up to that point."""
        node = _LLMWorkNode()
        node._config = {"configurable": {}}
        existing_artifacts: Dict[str, Any] = {
            "orchestrate.task_t1.draft": _make_artifact_ref(
                "orchestrate", "tasks/t1/draft.md"
            ),
            "orchestrate.task_t2.draft": _make_artifact_ref(
                "orchestrate", "tasks/t2/draft.md"
            ),
            "research.findings": _make_artifact_ref("research", "findings.json"),
        }
        state: Dict[str, Any] = {
            "session_id": "s1",
            "budget": _make_budget(remaining=0),
            "artifacts": existing_artifacts,
        }

        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, {})

        # Result output must NOT clear or overwrite artifacts
        assert "artifacts" not in result.output
        # Original state artifacts remain untouched
        assert len(state["artifacts"]) == 3
        assert "orchestrate.task_t1.draft" in state["artifacts"]

    @pytest.mark.asyncio
    async def test_sequential_work_then_exhaustion_preserves_artifacts(self) -> None:
        """Simulate multiple nodes producing artifacts, then budget exhaustion."""
        config: Dict[str, Any] = {"configurable": {}}
        budget = _make_budget(remaining=2)
        artifacts: Dict[str, Any] = {}

        # Node 1: produces artifact, decrements budget (remaining: 2 -> 1)
        node1 = _ArtifactProducingNode("task_t1.draft")
        node1._config = config
        state1: Dict[str, Any] = {"session_id": "s1", "budget": budget, "artifacts": artifacts}
        result1 = await node1._execute_async(state1, {})
        assert result1.status == NodeExecutionStatus.SUCCESS
        artifacts.update(result1.output.get("artifacts", {}))
        budget = result1.output.get("budget", budget)

        # Node 2: produces artifact, decrements budget (remaining: 1 -> 0)
        node2 = _ArtifactProducingNode("task_t2.draft")
        node2._config = config
        state2: Dict[str, Any] = {"session_id": "s1", "budget": budget, "artifacts": artifacts}
        result2 = await node2._execute_async(state2, {})
        assert result2.status == NodeExecutionStatus.SUCCESS
        artifacts.update(result2.output.get("artifacts", {}))
        budget = result2.output.get("budget", budget)

        # Node 3: budget is now 0, should catch BudgetExhaustedError
        node3 = _LLMWorkNode()
        node3._config = config
        state3: Dict[str, Any] = {"session_id": "s1", "budget": budget, "artifacts": artifacts}
        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result3 = await node3._execute_async(state3, {})

        assert result3.output["workflow_status"] == "budget_exhausted"
        # Both artifacts from earlier nodes are preserved
        assert "task_t1.draft" in artifacts
        assert "task_t2.draft" in artifacts
        assert len(artifacts) == 2


# ---------------------------------------------------------------------------
# Test: Budget monotonicity
# ---------------------------------------------------------------------------


class TestBudgetMonotonicity:
    """Verify budget counters change monotonically across a sequence of nodes."""

    @pytest.mark.asyncio
    async def test_remaining_calls_only_decrease(self) -> None:
        """Req 8.1: remaining_llm_calls only decreases across state transitions."""
        budget = _make_budget(remaining=5)
        remaining_history = [budget["remaining_llm_calls"]]

        for _ in range(5):
            budget = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=100)
            remaining_history.append(budget["remaining_llm_calls"])

        for i in range(1, len(remaining_history)):
            assert remaining_history[i] <= remaining_history[i - 1]

    @pytest.mark.asyncio
    async def test_tokens_used_only_increase(self) -> None:
        """Req 8.2: tokens_used only increases across state transitions."""
        budget = _make_budget(remaining=10)
        tokens_history = [budget["tokens_used"]]

        for _ in range(5):
            budget = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=500)
            tokens_history.append(budget["tokens_used"])

        for i in range(1, len(tokens_history)):
            assert tokens_history[i] >= tokens_history[i - 1]

    @pytest.mark.asyncio
    async def test_monotonicity_across_node_execution_sequence(self) -> None:
        """Full integration: run nodes in sequence, track budget monotonicity."""
        config: Dict[str, Any] = {"configurable": {}}
        budget = _make_budget(remaining=3)
        remaining_history = [budget["remaining_llm_calls"]]
        tokens_history = [budget["tokens_used"]]

        for _ in range(3):
            node = _LLMWorkNode(calls_per_step=1, tokens_per_step=1000)
            node._config = config
            state: Dict[str, Any] = {"session_id": "s1", "budget": budget, "artifacts": {}}
            result = await node._execute_async(state, {})
            budget = result.output.get("budget", budget)
            remaining_history.append(budget["remaining_llm_calls"])
            tokens_history.append(budget["tokens_used"])

        assert remaining_history == [3, 2, 1, 0]
        assert tokens_history == [0, 1000, 2000, 3000]
        assert BudgetGuard.is_exhausted(budget) is True


# ---------------------------------------------------------------------------
# Test: Route after budget — OrchestrateSubgraph routing
# ---------------------------------------------------------------------------


class TestRouteAfterBudgetIntegration:
    """Verify OrchestrateSubgraph routes to END when budget is exhausted."""

    def test_exhausted_budget_routes_to_end(self) -> None:
        state: Dict[str, Any] = {
            "budget": {"remaining_llm_calls": 0},
            "workflow_status": "running",
        }
        assert OrchestrateSubgraph._route_after_budget(state) == "__end__"

    def test_budget_exhausted_status_routes_to_end(self) -> None:
        state: Dict[str, Any] = {
            "budget": {"remaining_llm_calls": 100},
            "workflow_status": "budget_exhausted",
        }
        assert OrchestrateSubgraph._route_after_budget(state) == "__end__"

    def test_healthy_budget_routes_to_task_selector(self) -> None:
        state: Dict[str, Any] = {
            "budget": {"remaining_llm_calls": 50},
            "workflow_status": "running",
        }
        assert OrchestrateSubgraph._route_after_budget(state) == "task_selector"


# ---------------------------------------------------------------------------
# Test: End-to-end low budget scenario
# ---------------------------------------------------------------------------


class TestLowBudgetEndToEnd:
    """End-to-end: start with low budget, run nodes until exhaustion."""

    @pytest.mark.asyncio
    async def test_low_budget_workflow_graceful_stop(self) -> None:
        """Start with budget=1, produce one artifact, then exhaust on next node."""
        config: Dict[str, Any] = {"configurable": {}}
        budget = _make_budget(remaining=1)
        artifacts: Dict[str, Any] = {}

        # Step 1: Produce artifact (uses last remaining call)
        producer = _ArtifactProducingNode("task_t1.draft")
        producer._config = config
        state: Dict[str, Any] = {"session_id": "s1", "budget": budget, "artifacts": artifacts}
        result = await producer._execute_async(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS
        artifacts.update(result.output.get("artifacts", {}))
        budget = result.output["budget"]
        assert budget["remaining_llm_calls"] == 0
        assert "task_t1.draft" in artifacts

        # Step 2: Next node hits exhaustion
        worker = _LLMWorkNode()
        worker._config = config
        state = {"session_id": "s1", "budget": budget, "artifacts": artifacts}
        with patch(
            "graph_kb_api.websocket.plan_events.emit_error",
            new_callable=AsyncMock,
        ):
            result = await worker._execute_async(state, {})

        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "orchestrate"
        assert "task_t1.draft" in artifacts
        assert len(artifacts) == 1
