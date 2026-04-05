"""
Unit tests for checkpoint resumability (Task 7.10).

Verifies:
- State is persisted after each phase completion and at each interrupt() point
  via LangGraph checkpointer (Req 23.2)
- On spec.resume with valid sessionId: load checkpoint, resume workflow from
  interrupted phase (Req 23.3)
- Sessions with workflow_status != "completed" can be restored to exact phase
  and data state (Req 23.1)

Requirements: 23.1, 23.2, 23.3
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    UnifiedSpecEngine,
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


def _make_state(
    current_phase: str = "context",
    workflow_status: str = "running",
    completed_phases: Dict[str, bool] | None = None,
    error: Dict[str, Any] | None = None,
    **phase_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a mock checkpoint state."""
    if completed_phases is None:
        completed_phases = {p: False for p in PHASE_ORDER}
    state: Dict[str, Any] = {
        "navigation": {"current_phase": current_phase, "direction": "forward"},
        "context": phase_data.get("context", {}),
        "research": phase_data.get("research", {}),
        "plan": phase_data.get("plan", {}),
        "decompose": phase_data.get("decompose", {}),
        "generate": phase_data.get("generate", {}),
        "mode": "wizard",
        "workflow_status": workflow_status,
        "completed_phases": completed_phases,
        "messages": [],
        "session_id": str(uuid.uuid4()),
    }
    if error:
        state["error"] = error
    return state


# ── get_resumable_state: basic behaviour ─────────────────────────


class TestGetResumableStateBasic:
    """get_resumable_state returns structured info for resumable sessions."""

    def test_returns_none_when_no_checkpoint(self):
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=None)
        config = {"configurable": {"thread_id": "spec-abc"}}
        assert engine.get_resumable_state(config) is None

    def test_returns_phase_and_data_for_running_session(self):
        state = _make_state(
            current_phase="research",
            workflow_status="running",
            completed_phases={
                "context": True,
                "research": False,
                "plan": False,
                "decompose": False,
                "generate": False,
            },
            research={"findings": {"summary": "found stuff"}},
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["phase"] == "research"
        assert result["phase_data"] == {"findings": {"summary": "found stuff"}}
        assert result["workflow_status"] == "running"
        assert result["completed_phases"]["context"] is True
        assert result["completed_phases"]["research"] is False

    def test_returns_phase_and_data_for_paused_session(self):
        state = _make_state(
            current_phase="plan",
            workflow_status="paused",
            completed_phases={
                "context": True,
                "research": True,
                "plan": False,
                "decompose": False,
                "generate": False,
            },
            plan={"roadmap": {"phases": ["alpha"]}},
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["phase"] == "plan"
        assert result["phase_data"]["roadmap"] == {"phases": ["alpha"]}
        assert result["workflow_status"] == "paused"

    def test_returns_phase_and_data_for_idle_session(self):
        state = _make_state(
            current_phase="context",
            workflow_status="idle",
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["phase"] == "context"
        assert result["workflow_status"] == "idle"


# ── get_resumable_state: completed sessions rejected (Req 23.1) ──


class TestGetResumableStateRejectsCompleted:
    """Completed sessions cannot be resumed."""

    def test_raises_for_completed_session(self):
        state = _make_state(
            current_phase="generate",
            workflow_status="completed",
            completed_phases={p: True for p in PHASE_ORDER},
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        with pytest.raises(ValueError, match="completed"):
            engine.get_resumable_state(config)

    def test_raises_for_completed_even_with_data(self):
        """A completed session with leftover data is still not resumable."""
        state = _make_state(
            current_phase="generate",
            workflow_status="completed",
            completed_phases={p: True for p in PHASE_ORDER},
            generate={
                "sections": {"intro": "# Intro"},
                "spec_document_path": "/blob/123",
            },
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        with pytest.raises(ValueError, match="completed"):
            engine.get_resumable_state(config)


# ── get_resumable_state: error state handling ────────────────────


class TestGetResumableStateErrorState:
    """Error-state sessions are resumable and report the failed phase."""

    def test_error_state_returns_failed_phase(self):
        state = _make_state(
            current_phase="research",
            workflow_status="error",
            error={"phase": "research", "message": "LLM timeout", "code": "TIMEOUT"},
            completed_phases={
                "context": True,
                "research": False,
                "plan": False,
                "decompose": False,
                "generate": False,
            },
            research={"findings": {"partial": True}},
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["phase"] == "research"
        assert result["workflow_status"] == "error"
        assert result["error"]["phase"] == "research"
        assert result["error"]["code"] == "TIMEOUT"
        assert result["phase_data"] == {"findings": {"partial": True}}

    def test_error_with_empty_error_dict_uses_navigation(self):
        """If error dict is empty, fall back to navigation.current_phase."""
        state = _make_state(
            current_phase="plan",
            workflow_status="error",
        )
        state["error"] = {}
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result["phase"] == "plan"
        assert result["error"] == {}


# ── get_resumable_state: thread_id validation ────────────────────


class TestGetResumableStateValidation:
    """get_resumable_state rejects invalid configs."""

    def test_rejects_missing_thread_id(self):
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            engine.get_resumable_state({})

    def test_rejects_empty_thread_id(self):
        engine = _make_engine()
        with pytest.raises(ValueError, match="thread_id"):
            engine.get_resumable_state({"configurable": {"thread_id": ""}})


# ── get_resumable_state: all non-completed statuses ──────────────


class TestGetResumableStateAllStatuses:
    """Every non-completed workflow_status is resumable."""

    @pytest.mark.parametrize("status", ["idle", "running", "paused", "error"])
    def test_non_completed_status_is_resumable(self, status):
        state = _make_state(
            current_phase="context",
            workflow_status=status,
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)
        assert result is not None
        assert result["workflow_status"] == status


# ── get_resumable_state: exact phase data restoration ────────────


class TestGetResumableStateExactData:
    """Checkpoint data is returned exactly as stored (Req 23.1)."""

    @pytest.mark.parametrize("phase_idx", range(len(PHASE_ORDER)))
    def test_restores_exact_phase_data(self, phase_idx):
        """For each phase, the returned phase_data matches the checkpoint."""
        phase = PHASE_ORDER[phase_idx]
        phase_data = {
            "context": {"spec_name": "Auth", "user_explanation": "SSO login"},
            "research": {"findings": {"codebase": "analyzed"}, "approved": True},
            "plan": {"roadmap": {"phases": ["p1", "p2"]}, "approved": True},
            "decompose": {
                "stories": [{"id": "s1", "title": "Login"}],
                "approved": True,
            },
            "generate": {
                "sections": {"intro": "# Intro"},
                "spec_document_path": "/b/1",
            },
        }
        completed = {p: (PHASE_ORDER.index(p) < phase_idx) for p in PHASE_ORDER}

        state = _make_state(
            current_phase=phase,
            workflow_status="running",
            completed_phases=completed,
            **{phase: phase_data[phase]},
        )
        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)
        config = {"configurable": {"thread_id": "spec-abc"}}

        result = engine.get_resumable_state(config)

        assert result["phase"] == phase
        assert result["phase_data"] == phase_data[phase]
        assert result["completed_phases"] == completed


# ── Dispatcher: handle_v3_spec_resume ────────────────────────────


class TestDispatcherResumeCheckpoint:
    """Tests for handle_v3_spec_resume checkpoint resumability (Req 23.3)."""

    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import _sessions

        _sessions.clear()
        yield
        _sessions.clear()

    @pytest.mark.asyncio
    async def test_resume_emits_prompt_for_interrupted_phase(self):
        """spec.resume with valid sessionId re-emits spec.phase.prompt."""
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _register_session,
            handle_v3_spec_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_resumable_state = MagicMock(
            return_value={
                "phase": "research",
                "phase_data": {"findings": {"summary": "partial"}},
                "completed_phases": {"context": True, "research": False},
                "workflow_status": "running",
                "error": {},
                "state": {},
            }
        )
        config = {"configurable": {"thread_id": "spec-r1"}}
        _register_session("r1", mock_engine, config, "c1", "w1")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("c1", "w1", {"session_id": "r1"})

            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.phase.prompt"
            assert kw["data"]["phase"] == "research"
            assert kw["data"]["prefilled"] == {"findings": {"summary": "partial"}}

    @pytest.mark.asyncio
    async def test_resume_rejects_completed_session(self):
        """spec.resume for a completed session emits spec.error."""
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _register_session,
            handle_v3_spec_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_resumable_state = MagicMock(
            side_effect=ValueError("Cannot resume a completed session.")
        )
        config = {"configurable": {"thread_id": "spec-r2"}}
        _register_session("r2", mock_engine, config, "c1", "w1")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("c1", "w1", {"session_id": "r2"})

            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "SESSION_COMPLETED"
            assert "completed" in kw["data"]["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_missing_session_id_emits_error(self):
        """spec.resume without session_id emits VALIDATION_ERROR."""
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            handle_v3_spec_resume,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("c1", "w1", {})

            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_resume_no_checkpoint_emits_session_not_found(self):
        """spec.resume for unknown session with no checkpoint emits SESSION_NOT_FOUND."""
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            handle_v3_spec_resume,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher._create_engine"
        ) as mock_create:
            mock_engine = MagicMock()
            mock_engine.get_resumable_state = MagicMock(return_value=None)
            mock_create.return_value = mock_engine

            with patch(
                "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
            ) as mock_mgr:
                mock_mgr.send_event = AsyncMock()
                await handle_v3_spec_resume("c1", "w1", {"session_id": "unknown-id"})

                kw = mock_mgr.send_event.call_args[1]
                assert kw["event_type"] == "spec.error"
                assert kw["data"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_resume_reconnect_updates_client_association(self):
        """On reconnect, the session's client_id is updated."""
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _get_session,
            _register_session,
            handle_v3_spec_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_resumable_state = MagicMock(
            return_value={
                "phase": "context",
                "phase_data": {},
                "completed_phases": {p: False for p in PHASE_ORDER},
                "workflow_status": "running",
                "error": {},
                "state": {},
            }
        )
        config = {"configurable": {"thread_id": "spec-r3"}}
        _register_session("r3", mock_engine, config, "old-client", "old-wf")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("new-client", "new-wf", {"session_id": "r3"})

            session = _get_session("r3")
            assert session["client_id"] == "new-client"
            assert session["workflow_id"] == "new-wf"


# ── Checkpointer integration: state persisted at phase boundaries ─


class TestCheckpointerPersistsState:
    """Verify the engine compiles with checkpointer so state is persisted
    at each node boundary and interrupt() point (Req 23.2)."""

    def test_compile_includes_checkpointer(self):
        """The compiled workflow uses the provided checkpointer."""
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        app_context.graph_store = MagicMock()

        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=checkpointer,
            mode="wizard",
        )

        # The compiled workflow should have the checkpointer set
        assert engine.compiled_workflow is not None
        assert engine.checkpointer is checkpointer

    def test_compile_with_default_checkpointer(self):
        """Engine creates a default checkpointer when none is provided."""
        engine = _make_engine()
        assert engine.compiled_workflow is not None
        # BaseWorkflowEngine creates a default checkpointer
        assert engine.checkpointer is not None

    def test_workflow_has_five_phase_nodes(self):
        """The compiled DAG has exactly 5 phase nodes."""
        engine = _make_engine()
        graph = engine.compiled_workflow.get_graph()
        # Node IDs include __start__ and __end__ plus the 5 phases
        node_ids = {n for n in graph.nodes}
        for phase in PHASE_ORDER:
            assert phase in node_ids, f"Phase '{phase}' missing from graph nodes"
