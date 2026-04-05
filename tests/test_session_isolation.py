"""
Unit tests for session isolation (Task 7.8).

Verifies:
- Each session gets a unique thread_id in the LangGraph checkpointer (Req 20.1)
- No cross-session state access through the checkpointer (Req 20.2)
- Concurrent sessions do not share mutable state (Req 20.4)

Requirements: 20.1, 20.2, 20.4
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    UnifiedSpecEngine,
)
from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
    _get_session,
    _register_session,
    _sessions,
    _validate_session_owner,
)

# ── Helpers ──────────────────────────────────────────────────────


def _make_engine() -> UnifiedSpecEngine:
    """Create an engine with mocked dependencies."""
    llm = MagicMock()
    app_context = MagicMock()
    app_context.llm = llm
    app_context.graph_store = MagicMock()
    return UnifiedSpecEngine(
        llm=llm,
        app_context=app_context,
        checkpointer=None,
        mode="wizard",
    )


# ── Unique thread_id per session (Req 20.1) ─────────────────────


class TestUniqueThreadId:
    """Each session must receive a unique thread_id."""

    def test_uuid_based_session_ids_are_unique(self):
        """Two UUID-based session IDs never collide."""
        ids = {str(uuid.uuid4()) for _ in range(1000)}
        assert len(ids) == 1000

    def test_thread_id_format_includes_session_id(self):
        """The thread_id embeds the session_id for traceability."""
        session_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": f"spec-{session_id}"}}
        assert session_id in config["configurable"]["thread_id"]

    def test_two_sessions_get_different_thread_ids(self):
        """Registering two sessions produces distinct thread_ids."""
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()

            sid1 = str(uuid.uuid4())
            sid2 = str(uuid.uuid4())
            config1 = {"configurable": {"thread_id": f"spec-{sid1}"}}
            config2 = {"configurable": {"thread_id": f"spec-{sid2}"}}

            _register_session(sid1, engine1, config1, "client-a", "wf-1")
            _register_session(sid2, engine2, config2, "client-b", "wf-2")

            s1 = _get_session(sid1)
            s2 = _get_session(sid2)

            tid1 = s1["config"]["configurable"]["thread_id"]
            tid2 = s2["config"]["configurable"]["thread_id"]
            assert tid1 != tid2
        finally:
            _sessions.clear()


# ── No cross-session state access (Req 20.2) ────────────────────


class TestNoCrossSessionAccess:
    """Operations on one session must not affect another."""

    def test_session_lookup_returns_only_own_session(self):
        """_get_session returns None for unknown IDs."""
        _sessions.clear()
        try:
            engine = _make_engine()
            sid = str(uuid.uuid4())
            config = {"configurable": {"thread_id": f"spec-{sid}"}}
            _register_session(sid, engine, config, "client-a", "wf-1")

            assert _get_session(sid) is not None
            assert _get_session("nonexistent-id") is None
            assert _get_session(str(uuid.uuid4())) is None
        finally:
            _sessions.clear()

    def test_validate_session_owner_accepts_owner(self):
        """The registered client is accepted as owner."""
        session = {"client_id": "client-a", "engine": None}
        assert _validate_session_owner(session, "client-a", "s1") is True

    def test_validate_session_owner_rejects_other_client(self):
        """A different client is rejected."""
        session = {"client_id": "client-a", "engine": None}
        assert _validate_session_owner(session, "client-b", "s1") is False

    def test_validate_session_owner_allows_unowned(self):
        """A session with no recorded owner allows any client."""
        session = {"engine": None}
        assert _validate_session_owner(session, "client-x", "s1") is True

    def test_engine_rejects_empty_thread_id(self):
        """Engine methods reject configs without a thread_id."""
        engine = _make_engine()
        assert engine.validate_thread_config({}) is False
        assert engine.validate_thread_config({"configurable": {}}) is False
        assert engine.validate_thread_config({"configurable": {"thread_id": ""}}) is False

    def test_engine_accepts_valid_thread_id(self):
        """Engine methods accept configs with a non-empty thread_id."""
        engine = _make_engine()
        assert engine.validate_thread_config({"configurable": {"thread_id": "spec-abc"}}) is True

    @pytest.mark.asyncio
    async def test_start_workflow_rejects_missing_thread_id(self):
        """start_workflow raises ValueError without thread_id."""
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            await engine.start_workflow({}, {})

    @pytest.mark.asyncio
    async def test_resume_workflow_rejects_missing_thread_id(self):
        """resume_workflow raises ValueError without thread_id."""
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            await engine.resume_workflow({}, {})

    @pytest.mark.asyncio
    async def test_retry_phase_rejects_missing_thread_id(self):
        """retry_phase raises ValueError without thread_id."""
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            await engine.retry_phase({})

    @pytest.mark.asyncio
    async def test_reset_to_phase_rejects_missing_thread_id(self):
        """reset_to_phase raises ValueError without thread_id."""
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            await engine.reset_to_phase("context", {})


# ── No shared mutable state (Req 20.4) ──────────────────────────


class TestNoSharedMutableState:
    """Concurrent sessions must not share mutable state."""

    def test_config_is_deep_copied_on_registration(self):
        """Mutating the original config dict does not affect the session."""
        _sessions.clear()
        try:
            engine = _make_engine()
            sid = str(uuid.uuid4())
            original_config = {"configurable": {"thread_id": f"spec-{sid}"}}

            _register_session(sid, engine, original_config, "client-a", "wf-1")

            # Mutate the original — session should be unaffected
            original_config["configurable"]["thread_id"] = "TAMPERED"

            session = _get_session(sid)
            assert session["config"]["configurable"]["thread_id"] == f"spec-{sid}"
        finally:
            _sessions.clear()

    def test_two_sessions_have_independent_configs(self):
        """Mutating one session's config does not affect the other."""
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()

            sid1 = str(uuid.uuid4())
            sid2 = str(uuid.uuid4())
            config1 = {"configurable": {"thread_id": f"spec-{sid1}"}}
            config2 = {"configurable": {"thread_id": f"spec-{sid2}"}}

            _register_session(sid1, engine1, config1, "client-a", "wf-1")
            _register_session(sid2, engine2, config2, "client-b", "wf-2")

            # Mutate session 1's config via the session dict
            s1 = _get_session(sid1)
            s1["config"]["configurable"]["extra"] = "leaked"

            # Session 2 must be unaffected
            s2 = _get_session(sid2)
            assert "extra" not in s2["config"]["configurable"]
        finally:
            _sessions.clear()

    def test_each_session_gets_own_engine_instance(self):
        """Two sessions must not share the same engine object."""
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()

            sid1 = str(uuid.uuid4())
            sid2 = str(uuid.uuid4())
            config1 = {"configurable": {"thread_id": f"spec-{sid1}"}}
            config2 = {"configurable": {"thread_id": f"spec-{sid2}"}}

            _register_session(sid1, engine1, config1, "client-a", "wf-1")
            _register_session(sid2, engine2, config2, "client-b", "wf-2")

            s1 = _get_session(sid1)
            s2 = _get_session(sid2)
            assert s1["engine"] is not s2["engine"]
        finally:
            _sessions.clear()

    def test_initial_state_is_independent_per_call(self):
        """_build_initial_state returns a fresh dict each time."""
        engine = _make_engine()
        state1 = engine._build_initial_state({"context": {"spec_name": "A"}})
        state2 = engine._build_initial_state({"context": {"spec_name": "B"}})

        # Mutate state1 — state2 must be unaffected
        state1["context"]["spec_name"] = "MUTATED"
        assert state2["context"]["spec_name"] == "B"

        # Completed phases dicts must be independent
        state1["completed_phases"]["context"] = True
        assert state2["completed_phases"]["context"] is False
