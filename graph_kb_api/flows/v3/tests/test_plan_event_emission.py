"""Tests for extended event emission helpers in plan_events.py.

Validates Requirements 21.1–21.7: each helper emits the correct event_type,
includes the correct data fields, and gracefully handles a missing ws_manager.
"""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from graph_kb_api.websocket import plan_events
from graph_kb_api.websocket.plan_events import (
    emit_budget_warning,
    emit_complete,
    emit_error,
    emit_phase_complete,
    emit_phase_enter,
    emit_task_complete,
    emit_task_critique,
    emit_task_start,
)

SESSION = "test-session-123"
CLIENT = "client-abc"


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def mock_ws():
    """Provide a mock WebSocket manager and patch it into plan_events."""
    ws = AsyncMock()
    with patch.object(plan_events, "_plan_ws_manager", ws):
        yield ws


@pytest.fixture()
def no_ws():
    """Ensure no WebSocket manager is set."""
    with patch.object(plan_events, "_plan_ws_manager", None):
        yield


# ── plan.phase.enter ─────────────────────────────────────────────


class TestEmitPhaseEnter:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_phase_enter(SESSION, "research", 6)
        mock_ws.broadcast_to_session.assert_awaited_once()
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.phase.enter"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_phase_enter(SESSION, "context", 4)
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["session_id"] == SESSION
        assert data["phase"] == "context"
        assert data["expected_steps"] == 4

    @pytest.mark.asyncio
    async def test_uses_send_event_with_client_id(self, mock_ws):
        await emit_phase_enter(SESSION, "planning", 7, client_id=CLIENT)
        mock_ws.send_event.assert_awaited_once()
        call_kw = mock_ws.send_event.call_args.kwargs
        assert call_kw["client_id"] == CLIENT
        assert call_kw["event_type"] == "plan.phase.enter"

    @pytest.mark.asyncio
    async def test_graceful_without_ws(self, no_ws, caplog):
        with caplog.at_level(logging.DEBUG):
            await emit_phase_enter(SESSION, "research", 6)
        assert "plan.phase.enter" in caplog.text or "Plan event" in caplog.text


# ── plan.phase.complete ──────────────────────────────────────────


class TestEmitPhaseComplete:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_phase_complete(SESSION, "research", "Done", 12.5)
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.phase.complete"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_phase_complete(SESSION, "assembly", "Assembled", 30.0)
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["phase"] == "assembly"
        assert data["result_summary"] == "Assembled"
        assert data["duration_s"] == 30.0

    @pytest.mark.asyncio
    async def test_graceful_without_ws(self, no_ws, caplog):
        with caplog.at_level(logging.DEBUG):
            await emit_phase_complete(SESSION, "context", "ok", 1.0)


# ── plan.task.start ──────────────────────────────────────────────


class TestEmitTaskStart:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_task_start(SESSION, "t1", "Build API")
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.task.start"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_task_start(SESSION, "t2", "Write tests")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["task_id"] == "t2"
        assert data["task_name"] == "Write tests"


# ── plan.task.critique ───────────────────────────────────────────


class TestEmitTaskCritique:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_task_critique(SESSION, "t1", True, "Looks good")
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.task.critique"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_task_critique(SESSION, "t1", False, "Needs revision")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["task_id"] == "t1"
        assert data["passed"] is False
        assert data["feedback"] == "Needs revision"


# ── plan.task.complete ───────────────────────────────────────────


class TestEmitTaskComplete:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_task_complete(SESSION, "t3")
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.task.complete"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_task_complete(SESSION, "t3")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["session_id"] == SESSION
        assert data["task_id"] == "t3"


# ── plan.budget.warning ─────────────────────────────────────────


class TestEmitBudgetWarning:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_budget_warning(SESSION, 0.15)
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.budget.warning"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_budget_warning(SESSION, 0.10)
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["budget_remaining_pct"] == 0.10
        assert "message" in data
        assert "10%" in data["message"]


# ── plan.error ───────────────────────────────────────────────────


class TestEmitError:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_error(SESSION, "boom", "ENGINE_ERROR")
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.error"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_error(SESSION, "fail", "STORAGE_ERROR", phase="research")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["message"] == "fail"
        assert data["code"] == "STORAGE_ERROR"
        assert data["phase"] == "research"

    @pytest.mark.asyncio
    async def test_omits_phase_when_none(self, mock_ws):
        await emit_error(SESSION, "oops", "UNKNOWN")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert "phase" not in data

    @pytest.mark.asyncio
    async def test_graceful_without_ws(self, no_ws, caplog):
        with caplog.at_level(logging.DEBUG):
            await emit_error(SESSION, "err", "CODE")


# ── plan.complete ────────────────────────────────────────────────


class TestEmitComplete:
    @pytest.mark.asyncio
    async def test_emits_correct_event_type(self, mock_ws):
        await emit_complete(SESSION, None, "https://example.com/spec.md")
        call_kw = mock_ws.broadcast_to_session.call_args.kwargs
        assert call_kw["event_type"] == "plan.complete"

    @pytest.mark.asyncio
    async def test_includes_required_fields(self, mock_ws):
        await emit_complete(SESSION, None, "https://x.com/spec.md", "https://x.com/stories")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert data["session_id"] == SESSION
        assert data["spec_document_url"] == "https://x.com/spec.md"
        assert data["story_cards_url"] == "https://x.com/stories"

    @pytest.mark.asyncio
    async def test_omits_story_cards_when_none(self, mock_ws):
        await emit_complete(SESSION, None, "https://x.com/spec.md")
        data = mock_ws.broadcast_to_session.call_args.kwargs["data"]
        assert "story_cards_url" not in data

    @pytest.mark.asyncio
    async def test_graceful_without_ws(self, no_ws, caplog):
        with caplog.at_level(logging.DEBUG):
            await emit_complete(SESSION, None, "https://x.com/spec.md")


# ── Cross-cutting: ws_manager exception handling ─────────────────


class TestWsManagerExceptionHandling:
    @pytest.mark.asyncio
    async def test_broadcast_exception_is_swallowed(self, mock_ws):
        mock_ws.broadcast_to_session.side_effect = RuntimeError("ws down")
        # Should not raise
        await emit_phase_enter(SESSION, "context", 4)

    @pytest.mark.asyncio
    async def test_send_event_exception_is_swallowed(self, mock_ws):
        mock_ws.send_event.side_effect = RuntimeError("ws down")
        await emit_phase_enter(SESSION, "context", 4, client_id=CLIENT)
