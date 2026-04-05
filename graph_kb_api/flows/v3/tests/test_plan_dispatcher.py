"""Tests for PlanDispatcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher
from graph_kb_api.websocket.plan_events import PlanStartPayload


@pytest.fixture
def dispatcher():
    """Create PlanDispatcher."""
    return PlanDispatcher()


class TestPlanDispatcherInit:
    """Test PlanDispatcher initialization."""

    def test_dispatcher_initialization(self, dispatcher):
        assert dispatcher._sessions == {}


class TestPlanDispatcherCreateEngine:
    """Test PlanDispatcher._create_engine method."""

    @patch("graph_kb_api.websocket.handlers.plan_dispatcher.CheckpointerFactory")
    @patch("graph_kb_api.websocket.handlers.plan_dispatcher.get_app_context")
    def test_create_engine_returns_plan_engine(
        self, mock_get_app_context, mock_checkpointer_factory, dispatcher
    ):
        mock_app_context = MagicMock()
        mock_app_context.checkpointer = None
        mock_get_app_context.return_value = mock_app_context
        mock_checkpointer_factory.create_checkpointer.return_value = None

        engine, progress_callback = dispatcher._create_engine(
            client_id="client-1",
            workflow_id="wf-1",
            session_id="session-1",
        )

        assert engine is not None
        assert progress_callback is not None


class TestPlanDispatcherWorkflow:
    """Test PlanDispatcher workflow execution."""

    @pytest.mark.asyncio
    async def test_handle_start_validates_payload(self, dispatcher):
        """Invalid payload triggers validation error."""
        dispatcher._emit_plan_error = AsyncMock()

        await dispatcher.handle_start("client-1", "wf-1", {"invalid_field": True})

        dispatcher._emit_plan_error.assert_called_once()
        assert dispatcher._emit_plan_error.call_args[0][3] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    @patch("graph_kb_api.websocket.handlers.plan_dispatcher.CheckpointerFactory")
    @patch("graph_kb_api.websocket.handlers.plan_dispatcher.get_app_context")
    async def test_handle_start_creates_engine_and_session(
        self, mock_get_app_context, mock_checkpointer_factory, dispatcher
    ):
        mock_app_context = MagicMock()
        mock_app_context.checkpointer = None
        mock_get_app_context.return_value = mock_app_context
        mock_checkpointer_factory.create_checkpointer.return_value = None

        payload = PlanStartPayload(name="Test Plan")

        dispatcher._persist_session_to_db = AsyncMock()

        await dispatcher.handle_start("client-1", "wf-1", payload.model_dump())

        # Verify a session was registered
        assert len(dispatcher._sessions) == 1


class TestPlanDispatcherProgressPersistence:
    """Regression tests for session persistence during live phase progress."""

    @pytest.mark.asyncio
    async def test_progress_callback_persists_current_phase(self, dispatcher):
        with (
            patch.object(PlanDispatcher, "_emit_phase_progress", new=AsyncMock()),
            patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock,
        ):
            callback = dispatcher._make_progress_callback(
                "client-1",
                "wf-1",
                session_id="session-1",
                thread_id="plan-session-1",
                user_id="client-1",
            )

            await callback({"phase": "orchestrate", "message": "Working task graph"})

        persist_mock.assert_awaited_once()
        _, kwargs = persist_mock.await_args
        assert kwargs["current_phase"] == "orchestrate"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
            "planning": True,
        }
