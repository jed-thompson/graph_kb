"""Integration tests: WebSocket event schema validation.

Run mock SubgraphAwareNode instances that emit various event types via
progress callbacks, capture all emitted events, and validate each event
matches the SubgraphProgressData Pydantic model.

Tests cover all plan.* event types:
- plan.phase.enter
- plan.phase.progress
- plan.phase.complete
- plan.error
- plan.budget.warning

**Validates: Requirements 13.1, 13.2, 21.1, 21.2**
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.websocket import plan_events
from graph_kb_api.websocket.plan_events import (
    SubgraphProgressData,
    emit_budget_warning,
    emit_complete,
    emit_error,
    emit_phase_complete,
    emit_phase_enter,
    emit_phase_progress,
)

# ---------------------------------------------------------------------------
# Helpers — event capture infrastructure
# ---------------------------------------------------------------------------


class EventCapture:
    """Captures events emitted via the mock WebSocket manager."""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    def record(self, event_type: str, data: Dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, "data": data})

    def get_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["event_type"] == event_type]


def _make_capturing_ws(capture: EventCapture) -> AsyncMock:
    """Create a mock WebSocket manager that records all emitted events."""
    ws = AsyncMock()

    async def _broadcast(session_id: str, event_type: str, data: Dict[str, Any]):
        capture.record(event_type, data)

    async def _send(
        client_id: str,
        event_type: str,
        workflow_id: str,
        data: Dict[str, Any],
    ):
        capture.record(event_type, data)

    ws.broadcast_to_session = AsyncMock(side_effect=_broadcast)
    ws.send_event = AsyncMock(side_effect=_send)
    return ws


# ---------------------------------------------------------------------------
# Mock nodes that emit events via progress callback
# ---------------------------------------------------------------------------


class ProgressEmittingNode(SubgraphAwareNode):
    """Node that emits a progress event and returns success."""

    def __init__(
        self,
        phase: str = "research",
        step_name: str = "dispatch_research",
        step_progress: float = 0.5,
    ):
        super().__init__(node_name=step_name)
        self.phase = phase
        self.step_name = step_name
        self.step_progress = step_progress

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output={"done": True})


class MultiEventNode(SubgraphAwareNode):
    """Node that emits multiple event types during execution."""

    def __init__(self):
        super().__init__(node_name="multi_event")
        self.phase = "orchestrate"
        self.step_name = "worker"
        self.step_progress = 0.6

    async def _execute_step(self, state, config):
        session_id = state.get("session_id", "")
        # Emit task-level progress via emit_phase_progress
        await emit_phase_progress(
            session_id=session_id,
            phase=self.phase,
            step=self.step_name,
            message="Processing task 2/5",
            progress_pct=0.4,
            task_id="task-2",
            task_progress="2/5 tasks complete",
            iteration=1,
            max_iterations=3,
            agent_type="backend",
            confidence=0.85,
        )
        return NodeExecutionResult.success(output={"tasks_done": 2})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SESSION = "integration-event-session"
CLIENT = "client-evt-1"


@pytest.fixture()
def capture():
    return EventCapture()


@pytest.fixture()
def mock_ws(capture):
    ws = _make_capturing_ws(capture)
    with patch.object(plan_events, "_plan_ws_manager", ws):
        yield ws


# ---------------------------------------------------------------------------
# Tests: SubgraphAwareNode auto-emits progress matching schema (Req 13.1, 21.2)
# ---------------------------------------------------------------------------


class TestNodeProgressEventSchema:
    """Verify SubgraphAwareNode auto-emitted progress matches SubgraphProgressData."""

    @pytest.mark.asyncio
    async def test_auto_progress_has_required_fields(self):
        """Req 13.1: SubgraphProgressData has session_id, phase, step, message, percent."""
        node = ProgressEmittingNode(phase="research", step_name="aggregate", step_progress=0.65)
        captured = []

        async def cb(data):
            captured.append(data)

        node._config = {"configurable": {"progress_callback": cb}}
        state = {"session_id": SESSION, "budget": {}}

        await node._execute_async(state, {})

        assert len(captured) == 1
        evt = captured[0]
        assert evt["session_id"] == SESSION
        assert evt["phase"] == "research"
        assert evt["step"] == "aggregate"
        assert "message" in evt
        assert evt["percent"] == 0.65

    @pytest.mark.asyncio
    async def test_auto_progress_validates_as_subgraph_progress_data(self):
        """Req 13.1, 13.2: Auto-emitted event validates against Pydantic model."""
        node = ProgressEmittingNode(phase="context", step_name="validate_context", step_progress=0.0)
        captured = []

        async def cb(data):
            captured.append(data)

        node._config = {"configurable": {"progress_callback": cb}}
        state = {"session_id": SESSION, "budget": {}}

        await node._execute_async(state, {})

        evt = captured[0]
        # Should validate without error
        validated = SubgraphProgressData(**evt)
        assert validated.session_id == SESSION
        assert validated.phase.value == "context"
        assert validated.percent == 0.0

    @pytest.mark.asyncio
    async def test_percent_within_bounds(self):
        """Req 13.2: percent must be between 0.0 and 1.0 inclusive."""
        for progress in [0.0, 0.25, 0.5, 0.75, 1.0]:
            node = ProgressEmittingNode(step_progress=progress)
            captured = []

            async def cb(data):
                captured.append(data)

            node._config = {"configurable": {"progress_callback": cb}}
            state = {"session_id": SESSION, "budget": {}}

            await node._execute_async(state, {})

            validated = SubgraphProgressData(**captured[0])
            assert 0.0 <= validated.percent <= 1.0

    @pytest.mark.asyncio
    async def test_invalid_percent_rejected_by_model(self):
        """Req 13.2: percent outside [0.0, 1.0] is rejected by Pydantic."""
        with pytest.raises(ValidationError):
            SubgraphProgressData(
                session_id="s1",
                phase="research",
                step="test",
                message="bad",
                percent=1.5,
            )
        with pytest.raises(ValidationError):
            SubgraphProgressData(
                session_id="s1",
                phase="research",
                step="test",
                message="bad",
                percent=-0.1,
            )


# ---------------------------------------------------------------------------
# Tests: emit_phase_progress with optional fields validates schema (Req 13.3)
# ---------------------------------------------------------------------------


class TestEmitPhaseProgressEventSchema:
    """Verify emit_phase_progress events match SubgraphProgressData schema."""

    @pytest.mark.asyncio
    async def test_minimal_progress_event_validates(self, mock_ws, capture):
        """Req 13.1: Minimal event with only required fields validates."""
        await emit_phase_progress(
            session_id=SESSION,
            phase="planning",
            step="roadmap",
            message="Building roadmap",
            progress_pct=0.2,
        )

        assert len(capture.events) == 1
        data = capture.events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["percent"] == 0.2
        assert "message" in data

    @pytest.mark.asyncio
    async def test_full_progress_event_validates(self, mock_ws, capture):
        """Req 13.3: Event with all optional fields validates."""
        await emit_phase_progress(
            session_id=SESSION,
            phase="orchestrate",
            step="worker",
            message="Executing task",
            progress_pct=0.6,
            client_id=CLIENT,
            substep="writing code",
            task_id="task-3",
            task_progress="3/8 tasks complete",
            iteration=2,
            max_iterations=5,
            agent_type="backend",
            confidence=0.92,
        )

        assert len(capture.events) == 1
        data = capture.events[0]["data"]
        assert data["substep"] == "writing code"
        assert data["task_id"] == "task-3"
        assert data["task_progress"] == "3/8 tasks complete"
        assert data["iteration"] == 2
        assert data["max_iterations"] == 5
        assert data["agent_type"] == "backend"
        assert data["confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_optional_fields_omitted_when_not_provided(self, mock_ws, capture):
        """Req 13.3: Optional fields absent from payload when not provided."""
        await emit_phase_progress(
            session_id=SESSION,
            phase="context",
            step="collect",
            message="Collecting",
            progress_pct=0.1,
        )

        data = capture.events[0]["data"]
        optional_keys = [
            "substep",
            "task_id",
            "task_progress",
            "iteration",
            "max_iterations",
            "agent_type",
            "confidence",
        ]
        for key in optional_keys:
            assert key not in data, f"Optional field '{key}' should be absent"


# ---------------------------------------------------------------------------
# Tests: plan.phase.enter event schema (Req 21.1)
# ---------------------------------------------------------------------------


class TestPhaseEnterEventSchema:
    """Verify plan.phase.enter events have correct structure."""

    @pytest.mark.asyncio
    async def test_phase_enter_event_type(self, mock_ws, capture):
        """Req 21.1: plan.phase.enter emitted on subgraph entry."""
        await emit_phase_enter(SESSION, "research", 6)

        events = capture.get_by_type("plan.phase.enter")
        assert len(events) == 1
        data = events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["phase"] == "research"
        assert data["expected_steps"] == 6

    @pytest.mark.asyncio
    async def test_phase_enter_for_all_phases(self, mock_ws, capture):
        """Req 21.1: plan.phase.enter works for all valid phases."""
        phases = ["context", "research", "plan", "orchestrate", "completeness"]
        for i, phase in enumerate(phases):
            await emit_phase_enter(SESSION, phase, i + 3)

        events = capture.get_by_type("plan.phase.enter")
        assert len(events) == len(phases)
        for i, evt in enumerate(events):
            assert evt["data"]["phase"] == phases[i]


# ---------------------------------------------------------------------------
# Tests: plan.phase.complete event schema (Req 21.2)
# ---------------------------------------------------------------------------


class TestPhaseCompleteEventSchema:
    """Verify plan.phase.complete events have correct structure."""

    @pytest.mark.asyncio
    async def test_phase_complete_event_type(self, mock_ws, capture):
        """Req 21.2: plan.phase.complete emitted on subgraph exit."""
        await emit_phase_complete(SESSION, "research", "Research done", 15.3)

        events = capture.get_by_type("plan.phase.complete")
        assert len(events) == 1
        data = events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["phase"] == "research"
        assert data["result_summary"] == "Research done"
        assert data["duration_s"] == 15.3


# ---------------------------------------------------------------------------
# Tests: plan.error event schema (Req 21.7)
# ---------------------------------------------------------------------------


class TestErrorEventSchema:
    """Verify plan.error events have correct structure."""

    @pytest.mark.asyncio
    async def test_error_event_with_phase(self, mock_ws, capture):
        """Req 21.7: plan.error includes message, code, and phase."""
        await emit_error(SESSION, "Storage failed", "STORAGE_ERROR", phase="research")

        events = capture.get_by_type("plan.error")
        assert len(events) == 1
        data = events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["message"] == "Storage failed"
        assert data["code"] == "STORAGE_ERROR"
        assert data["phase"] == "research"

    @pytest.mark.asyncio
    async def test_error_event_without_phase(self, mock_ws, capture):
        """Req 21.7: plan.error omits phase when not provided."""
        await emit_error(SESSION, "Unknown error", "UNKNOWN")

        data = capture.events[0]["data"]
        assert "phase" not in data
        assert data["code"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Tests: plan.budget.warning event schema (Req 21.6)
# ---------------------------------------------------------------------------


class TestBudgetWarningEventSchema:
    """Verify plan.budget.warning events have correct structure."""

    @pytest.mark.asyncio
    async def test_budget_warning_event(self, mock_ws, capture):
        """Req 21.6: plan.budget.warning includes budget_remaining_pct."""
        await emit_budget_warning(SESSION, 0.15)

        events = capture.get_by_type("plan.budget.warning")
        assert len(events) == 1
        data = events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["budget_remaining_pct"] == 0.15
        assert "message" in data
        assert "15%" in data["message"]


# ---------------------------------------------------------------------------
# Tests: plan.complete event schema (Req 21.4)
# ---------------------------------------------------------------------------


class TestCompleteEventSchema:
    """Verify plan.complete events have correct structure."""

    @pytest.mark.asyncio
    async def test_complete_event_with_all_fields(self, mock_ws, capture):
        """Req 21.4: plan.complete includes session_id and URLs."""
        await emit_complete(SESSION, {}, "https://x.com/spec.md", "https://x.com/stories")

        events = capture.get_by_type("plan.complete")
        assert len(events) == 1
        data = events[0]["data"]
        assert data["session_id"] == SESSION
        assert data["spec_document_url"] == "https://x.com/spec.md"
        assert data["story_cards_url"] == "https://x.com/stories"

    @pytest.mark.asyncio
    async def test_complete_event_omits_optional_url(self, mock_ws, capture):
        """Req 21.4: story_cards_url omitted when not provided."""
        await emit_complete(SESSION, {}, "https://x.com/spec.md")

        data = capture.events[0]["data"]
        assert "story_cards_url" not in data


# ---------------------------------------------------------------------------
# Tests: Multi-event node emits all events with valid schemas (Req 21.2)
# ---------------------------------------------------------------------------


class TestMultiEventNodeIntegration:
    """Run a node that emits multiple event types and validate all schemas."""

    @pytest.mark.asyncio
    async def test_node_emits_progress_and_auto_progress(self, mock_ws, capture):
        """Req 21.2: Node auto-emits progress + explicit emit_phase_progress."""
        node = MultiEventNode()
        auto_captured = []

        async def cb(data):
            auto_captured.append(data)

        node._config = {"configurable": {"progress_callback": cb}}
        state = {"session_id": SESSION, "budget": {}}

        await node._execute_async(state, {})

        # Auto-emitted progress from SubgraphAwareNode._execute_async
        assert len(auto_captured) == 1
        auto_evt = auto_captured[0]
        validated_auto = SubgraphProgressData(**auto_evt)
        assert validated_auto.phase.value == "orchestrate"
        assert validated_auto.step == "worker"

        # Explicit emit_phase_progress from _execute_step
        progress_events = capture.get_by_type("plan.phase.progress")
        assert len(progress_events) == 1
        data = progress_events[0]["data"]
        assert data["task_id"] == "task-2"
        assert data["task_progress"] == "2/5 tasks complete"
        assert data["iteration"] == 1
        assert data["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_full_event_lifecycle(self, mock_ws, capture):
        """Req 21.1, 21.2: Simulate a full phase lifecycle with all event types."""
        # Phase enter
        await emit_phase_enter(SESSION, "orchestrate", 9)

        # Progress during execution
        await emit_phase_progress(
            session_id=SESSION,
            phase="orchestrate",
            step="budget_check",
            message="Checking budget",
            progress_pct=0.0,
        )
        await emit_phase_progress(
            session_id=SESSION,
            phase="orchestrate",
            step="worker",
            message="Executing task 1",
            progress_pct=0.3,
            task_id="t1",
            task_progress="1/3 tasks",
        )

        # Budget warning
        await emit_budget_warning(SESSION, 0.18)

        # Phase complete
        await emit_phase_complete(SESSION, "orchestrate", "All tasks done", 45.2)

        # Verify all event types captured
        assert len(capture.get_by_type("plan.phase.enter")) == 1
        assert len(capture.get_by_type("plan.phase.progress")) == 2
        assert len(capture.get_by_type("plan.budget.warning")) == 1
        assert len(capture.get_by_type("plan.phase.complete")) == 1
        assert len(capture.events) == 5

        # Validate progress events against SubgraphProgressData where applicable
        for evt in capture.get_by_type("plan.phase.progress"):
            data = evt["data"]
            assert "session_id" in data
            assert "percent" in data
            assert 0.0 <= data["percent"] <= 1.0


# ---------------------------------------------------------------------------
# Tests: SubgraphProgressData Pydantic model validation (Req 13.1, 13.2)
# ---------------------------------------------------------------------------


class TestSubgraphProgressDataModel:
    """Direct validation of SubgraphProgressData Pydantic model."""

    def test_required_fields_only(self):
        """Req 13.1: Model accepts only required fields."""
        data = SubgraphProgressData(
            session_id="s1",
            phase="context",
            step="validate",
            message="Validating",
            percent=0.1,
        )
        assert data.session_id == "s1"
        assert data.substep is None
        assert data.task_id is None

    def test_all_optional_fields(self):
        """Req 13.3: Model accepts all optional fields."""
        data = SubgraphProgressData(
            session_id="s1",
            phase="orchestrate",
            step="worker",
            message="Working",
            percent=0.5,
            substep="writing",
            task_id="t1",
            task_progress="1/3",
            iteration=2,
            max_iterations=5,
            agent_type="backend",
            confidence=0.9,
            budget_remaining_pct=0.75,
        )
        assert data.substep == "writing"
        assert data.budget_remaining_pct == 0.75

    def test_percent_boundary_zero(self):
        """Req 13.2: percent=0.0 is valid."""
        data = SubgraphProgressData(session_id="s1", phase="context", step="s", message="m", percent=0.0)
        assert data.percent == 0.0

    def test_percent_boundary_one(self):
        """Req 13.2: percent=1.0 is valid."""
        data = SubgraphProgressData(session_id="s1", phase="context", step="s", message="m", percent=1.0)
        assert data.percent == 1.0

    def test_missing_required_field_rejected(self):
        """Req 13.1: Missing required field raises ValidationError."""
        with pytest.raises(ValidationError):
            SubgraphProgressData(
                session_id="s1",
                phase="context",
                step="s",
                # message missing
                percent=0.5,
            )
