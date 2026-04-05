"""Tests for SubgraphAwareNode base class."""

import pytest

from graph_kb_api.flows.v3.models.node_models import (
    NodeExecutionResult,
    NodeExecutionStatus,
)
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode


@pytest.fixture(autouse=True)
def mock_langgraph_interrupt():
    """Mock LangGraph's interrupt() to prevent runtime errors in direct _execute_async tests."""
    from unittest.mock import patch
    with patch("graph_kb_api.flows.v3.nodes.subgraph_aware_node.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"decision": "accept_results"}
        yield mock_interrupt


class ConcreteTestNode(SubgraphAwareNode):
    """Concrete implementation for testing."""

    def __init__(self, phase="test_phase", step_name="test_step", step_progress=0.5):
        super().__init__(node_name=step_name)
        self.phase = phase
        self.step_name = step_name
        self.step_progress = step_progress

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output={"executed": True})


class TestSubgraphAwareNodeAttributes:
    """Test that SubgraphAwareNode has the required attributes."""

    def test_phase_attribute(self):
        node = ConcreteTestNode(phase="orchestrate")
        assert node.phase == "orchestrate"

    def test_step_name_attribute(self):
        node = ConcreteTestNode(step_name="budget_check")
        assert node.step_name == "budget_check"

    def test_step_progress_attribute(self):
        node = ConcreteTestNode(step_progress=0.75)
        assert node.step_progress == 0.75

    def test_extends_base_workflow_node_v3(self):
        from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3

        node = ConcreteTestNode()
        assert isinstance(node, BaseWorkflowNodeV3)


class TestSubgraphAwareNodeProgressEmission:
    """Test that _execute_async emits progress before delegating."""

    @pytest.mark.asyncio
    async def test_emits_progress_callback(self):
        node = ConcreteTestNode(phase="research", step_name="dispatch_research", step_progress=0.3)
        captured = []

        async def mock_progress_cb(data):
            captured.append(data)

        node._config = {"configurable": {"progress_callback": mock_progress_cb}}

        state = {"session_id": "sess-123"}
        await node._execute_async(state, {})

        assert len(captured) == 1
        assert captured[0]["session_id"] == "sess-123"
        assert captured[0]["phase"] == "research"
        assert captured[0]["step"] == "dispatch_research"
        assert captured[0]["message"] == "dispatch_research..."
        assert captured[0]["percent"] == 0.3

    @pytest.mark.asyncio
    async def test_no_callback_still_executes(self):
        node = ConcreteTestNode()
        node._config = {"configurable": {}}

        state = {"session_id": "sess-456"}
        result = await node._execute_async(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["executed"] is True
        assert "transition_log" in result.output

    @pytest.mark.asyncio
    async def test_no_config_still_executes(self):
        node = ConcreteTestNode()
        # _config not set at all

        state = {}
        result = await node._execute_async(state, {})

        assert result.status == NodeExecutionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_delegates_to_execute_step(self):
        call_log = []

        class TrackingNode(SubgraphAwareNode):
            def __init__(self):
                super().__init__(node_name="tracker")
                self.phase = "context"
                self.step_name = "collect"
                self.step_progress = 0.0

            async def _execute_step(self, state, config):
                call_log.append(("_execute_step", state, config))
                return NodeExecutionResult.success(output={"tracked": True})

        node = TrackingNode()
        config = {"configurable": {}}
        node._config = config

        result = await node._execute_async({"session_id": "s1"}, {})

        assert len(call_log) == 1
        assert call_log[0][0] == "_execute_step"
        assert call_log[0][1] == {"session_id": "s1"}
        assert call_log[0][2] == config
        assert result.output["tracked"] is True
        assert "transition_log" in result.output

    @pytest.mark.asyncio
    async def test_session_id_defaults_to_empty(self):
        node = ConcreteTestNode()
        captured = []

        async def mock_cb(data):
            captured.append(data)

        node._config = {"configurable": {"progress_callback": mock_cb}}

        # state without session_id
        await node._execute_async({}, {})

        assert captured[0]["session_id"] == ""


class TestSubgraphAwareNodeAbstract:
    """Test that _execute_step is abstract and must be implemented."""

    def test_cannot_instantiate_without_execute_step(self):
        class IncompleteNode(SubgraphAwareNode):
            pass

        with pytest.raises(TypeError):
            IncompleteNode(node_name="incomplete")


class TestSubgraphAwareNodeDisconnectionResilience:
    """Test fire-and-forget progress emission (Req 29.1, 29.2)."""

    @pytest.mark.asyncio
    async def test_progress_callback_exception_does_not_stop_execution(self):
        """Req 29.1, 29.2: If the progress callback raises (e.g. due to
        WebSocket disconnect), the node continues executing."""
        node = ConcreteTestNode(
            phase="research",
            step_name="dispatch",
            step_progress=0.5,
        )

        async def failing_progress_cb(data):
            raise ConnectionError("WebSocket disconnected")

        node._config = {"configurable": {"progress_callback": failing_progress_cb}}

        state = {"session_id": "sess-dc"}
        result = await node._execute_async(state, {})

        # Node should still complete successfully
        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["executed"] is True

    @pytest.mark.asyncio
    async def test_budget_exhaustion_with_failing_callback(self):
        """Req 29.2: Budget exhaustion handling works even when
        the progress callback fails (client disconnected)."""
        from graph_kb_api.flows.v3.services.budget_guard import (
            BudgetExhaustedError,
        )

        class BudgetExhaustNode(SubgraphAwareNode):
            def __init__(self):
                super().__init__(node_name="budget_node")
                self.phase = "orchestrate"
                self.step_name = "budget_check"
                self.step_progress = 0.0

            async def _execute_step(self, state, config):
                raise BudgetExhaustedError("LLM call limit reached")

        node = BudgetExhaustNode()

        async def failing_cb(data):
            raise ConnectionError("WebSocket disconnected")

        node._config = {"configurable": {"progress_callback": failing_cb}}

        state = {"session_id": "sess-budget", "budget": {}}
        result = await node._execute_async(state, {})

        # Should still return graceful completion
        assert result.output["workflow_status"] == "budget_exhausted"
        assert result.output["paused_phase"] == "orchestrate"

    @pytest.mark.asyncio
    async def test_assembly_accept_results_routes_to_finalize_state(self):
        """Assembly budget acceptance should continue toward finalization."""
        from graph_kb_api.flows.v3.services.budget_guard import (
            BudgetExhaustedError,
        )

        class AssemblyBudgetNode(SubgraphAwareNode):
            def __init__(self):
                super().__init__(node_name="assembly_budget_node")
                self.phase = "assembly"
                self.step_name = "validate"
                self.step_progress = 0.9

            async def _execute_step(self, state, config):
                raise BudgetExhaustedError("LLM call limit reached")

        node = AssemblyBudgetNode()
        node._config = {"configurable": {}}

        state = {
            "session_id": "sess-assembly",
            "budget": {},
            "completed_phases": {
                "context": True,
                "research": True,
                "planning": True,
                "orchestrate": True,
            },
            "completeness": {"validation": {"is_valid": True}},
        }

        result = await node._execute_async(state, {})

        assert result.output["workflow_status"] == "running"
        assert result.output["completed_phases"]["assembly"] is True
        assert result.output["completeness"]["approval_decision"] == "approve"
        assert result.output["completeness"]["accepted_budget_exhausted_results"] is True
        assert "error" not in result.output
        assert "paused_phase" not in result.output


# ── ArtifactStorageError Handling Tests (Task 13.3, Req 27.2) ────


class _StorageFailNode(SubgraphAwareNode):
    """Test node that raises ArtifactStorageError in _execute_step."""

    def __init__(self):
        super().__init__(node_name="storage_fail_node")
        self.phase = "research"
        self.step_name = "dispatch_research"
        self.step_progress = 0.4

    async def _execute_step(self, state, config):
        from graph_kb_api.flows.v3.services.artifact_service import (
            ArtifactStorageError,
        )

        raise ArtifactStorageError("Blob storage operation failed after 3 attempts")


class TestSubgraphAwareNodeStorageErrorPause:
    """Test SubgraphAwareNode catches ArtifactStorageError and pauses workflow.

    Validates Requirement 27.2: IF all retry attempts fail, THEN THE
    ArtifactService SHALL pause the workflow and emit a plan.error event
    for user intervention.
    """

    @pytest.mark.asyncio
    async def test_storage_error_pauses_workflow(self):
        """ArtifactStorageError sets workflow_status to 'paused'."""
        from unittest.mock import AsyncMock, patch

        node = _StorageFailNode()
        node._config = {"configurable": {}}
        state = {"session_id": "s1", "budget": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, None)

        assert result.status == NodeExecutionStatus.SUCCESS
        assert result.output["workflow_status"] == "paused"
        assert result.output["paused_phase"] == "research"

    @pytest.mark.asyncio
    async def test_storage_error_emits_spec_error_with_storage_error_code(self):
        """plan.error event is emitted with code=STORAGE_ERROR."""
        from unittest.mock import AsyncMock, patch

        node = _StorageFailNode()
        node._config = {"configurable": {"client_id": "c1"}}
        state = {"session_id": "s1", "budget": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_error",
            new_callable=AsyncMock,
        ) as mock_emit:
            await node._execute_async(state, None)

        mock_emit.assert_awaited_once()
        assert mock_emit.call_args.kwargs["code"] == "STORAGE_ERROR"
        assert mock_emit.call_args.kwargs["phase"] == "research"
        assert mock_emit.call_args.kwargs["session_id"] == "s1"
        assert "Storage failure" in mock_emit.call_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_storage_error_result_contains_error_dict(self):
        """Result output contains error dict with STORAGE_ERROR code and phase."""
        from unittest.mock import AsyncMock, patch

        node = _StorageFailNode()
        node._config = {"configurable": {}}
        state = {"session_id": "s1", "budget": {}}

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, None)

        error = result.output["error"]
        assert error["code"] == "STORAGE_ERROR"
        assert error["phase"] == "research"
        assert "Storage failure" in error["message"]

    @pytest.mark.asyncio
    async def test_storage_error_preserves_artifacts(self):
        """Storage error does not clear existing artifacts from state."""
        from unittest.mock import AsyncMock, patch

        node = _StorageFailNode()
        node._config = {"configurable": {}}
        state = {
            "session_id": "s1",
            "budget": {},
            "artifacts": {"research.findings": {"key": "k", "content_hash": "h"}},
        }

        with patch(
            "graph_kb_api.flows.v3.nodes.subgraph_aware_node.emit_error",
            new_callable=AsyncMock,
        ):
            result = await node._execute_async(state, None)

        # Result should NOT clear artifacts — only sets status fields
        assert "artifacts" not in result.output
        assert result.output["workflow_status"] == "paused"

    @pytest.mark.asyncio
    async def test_storage_error_with_failing_callback(self):
        """Storage error handling works even when progress callback fails."""
        node = _StorageFailNode()

        async def failing_cb(data):
            raise ConnectionError("WebSocket disconnected")

        node._config = {"configurable": {"progress_callback": failing_cb}}
        state = {"session_id": "s1", "budget": {}}

        result = await node._execute_async(state, None)

        assert result.output["workflow_status"] == "paused"
        assert result.output["paused_phase"] == "research"
