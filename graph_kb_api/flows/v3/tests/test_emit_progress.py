"""Tests for SubgraphAwareNode._emit_progress() helper.

Validates Requirements 5.1, 5.2, 5.5:
- Wraps progress emission in try/except that logs WARNING and continues
- No-op if ctx.progress_cb is None
- Emits correct payload shape
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.flows.v3.nodes.subgraph_aware_node import NodeContext, SubgraphAwareNode


# ---------------------------------------------------------------------------
# Concrete test node (SubgraphAwareNode is abstract)
# ---------------------------------------------------------------------------

class _TestNode(SubgraphAwareNode):
    def __init__(self, phase: str = "research"):
        self.phase = phase
        self.step_name = "test_step"
        self.step_progress = 0.0

    async def _execute_step(self, state, config):
        raise NotImplementedError


def _make_ctx(*, progress_cb=None, session_id="sess-1", phase="research"):
    """Build a minimal NodeContext for testing _emit_progress."""
    return NodeContext(
        services={},
        session_id=session_id,
        budget={},
        phase=phase,
        config={},
        configurable={},
        llm=None,
        artifact_service=None,
        workflow_context=None,
        client_id=None,
        progress_cb=progress_cb,
        db_session_factory=None,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestEmitProgressHappyPath:
    async def test_calls_progress_cb_with_correct_payload(self):
        """_emit_progress sends the expected dict to the callback."""
        captured = []

        async def mock_cb(data):
            captured.append(data)

        node = _TestNode(phase="planning")
        ctx = _make_ctx(progress_cb=mock_cb, session_id="sess-42", phase="planning")

        await node._emit_progress(ctx, "build_plan", 0.5, "Building plan...")

        assert len(captured) == 1
        assert captured[0] == {
            "session_id": "sess-42",
            "phase": "planning",
            "step": "build_plan",
            "message": "Building plan...",
            "percent": 0.5,
        }

    async def test_uses_self_phase_not_ctx_phase(self):
        """The phase in the payload comes from self.phase."""
        captured = []

        async def mock_cb(data):
            captured.append(data)

        node = _TestNode(phase="orchestrate")
        # ctx.phase differs from node.phase — node.phase should win
        ctx = _make_ctx(progress_cb=mock_cb, phase="research")

        await node._emit_progress(ctx, "step_x", 0.3, "msg")

        assert captured[0]["phase"] == "orchestrate"


# ---------------------------------------------------------------------------
# No-op when progress_cb is None
# ---------------------------------------------------------------------------

class TestEmitProgressNoop:
    async def test_noop_when_progress_cb_is_none(self):
        """No error and no side effects when progress_cb is None."""
        node = _TestNode()
        ctx = _make_ctx(progress_cb=None)
        # Should return without error
        result = await node._emit_progress(ctx, "step", 0.0, "msg")
        assert result is None

    async def test_noop_when_progress_cb_is_falsy(self):
        """Handles other falsy values gracefully (e.g. 0, False)."""
        node = _TestNode()
        ctx = _make_ctx(progress_cb=0)
        result = await node._emit_progress(ctx, "step", 0.0, "msg")
        assert result is None


# ---------------------------------------------------------------------------
# Exception swallowing (Req 5.2, 5.5)
# ---------------------------------------------------------------------------

class TestEmitProgressExceptionSwallowing:
    async def test_swallows_connection_error(self):
        """ConnectionError from callback is caught and logged."""
        async def failing_cb(data):
            raise ConnectionError("WebSocket disconnected")

        node = _TestNode(phase="assembly")
        ctx = _make_ctx(progress_cb=failing_cb)

        # Should not raise
        await node._emit_progress(ctx, "finalize", 0.9, "Finalizing...")

    async def test_swallows_runtime_error(self):
        async def failing_cb(data):
            raise RuntimeError("unexpected failure")

        node = _TestNode()
        ctx = _make_ctx(progress_cb=failing_cb)
        await node._emit_progress(ctx, "step", 0.5, "msg")

    async def test_swallows_type_error(self):
        async def failing_cb(data):
            raise TypeError("bad type")

        node = _TestNode()
        ctx = _make_ctx(progress_cb=failing_cb)
        await node._emit_progress(ctx, "step", 0.5, "msg")

    async def test_logs_warning_on_exception(self, caplog):
        """Verify a WARNING log is emitted when the callback fails."""
        async def failing_cb(data):
            raise ValueError("boom")

        node = _TestNode(phase="research")
        ctx = _make_ctx(progress_cb=failing_cb)

        with caplog.at_level(logging.WARNING):
            await node._emit_progress(ctx, "aggregate", 0.4, "Aggregating...")

        assert any(
            "Progress emission failed for research/aggregate" in record.message
            for record in caplog.records
        ), f"Expected warning log not found. Records: {[r.message for r in caplog.records]}"
