"""
Unit tests for error handling and recovery in the unified spec engine
and v3 dispatcher.

Covers:
- Phase nodes catch LLM/tool failures and set state.error
- spec.error event is emitted when a phase fails
- Retry of current phase without re-executing upstream phases
- WebSocket disconnect/reconnect with checkpoint resumption
- Error state is cleared on successful phase completion
- route_after_phase halts on error state

Requirements: 19.1, 19.2, 19.3, 19.4
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.graph import END

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    UnifiedSpecEngine,
    route_after_phase,
)
from graph_kb_api.flows.v3.nodes.spec_phases import (
    _make_error,
    research_phase,
    plan_phase,
    decompose_phase,
    generate_phase,
)


# ── _make_error helper ───────────────────────────────────────────


class TestMakeError:
    """Tests for the _make_error helper that builds error dicts."""

    def test_basic_error(self):
        exc = RuntimeError("LLM timeout")
        err = _make_error("research", exc)
        assert err["phase"] == "research"
        assert err["message"] == "LLM timeout"
        assert err["code"] == "PHASE_EXECUTION_ERROR"

    def test_custom_code(self):
        exc = ValueError("bad input")
        err = _make_error("plan", exc, code="CUSTOM_ERROR")
        assert err["phase"] == "plan"
        assert err["message"] == "bad input"
        assert err["code"] == "CUSTOM_ERROR"


# ── route_after_phase error handling ─────────────────────────────


class TestRouteAfterPhaseErrorHandling:
    """Tests that route_after_phase halts on error state (Req 19.1)."""

    def test_error_state_returns_end(self):
        state = {
            "workflow_status": "error",
            "navigation": {"current_phase": "research", "direction": "forward"},
        }
        assert route_after_phase(state) == END

    def test_running_state_routes_normally(self):
        state = {
            "workflow_status": "running",
            "navigation": {"current_phase": "research", "direction": "forward"},
        }
        assert route_after_phase(state) == "plan"

    def test_error_state_overrides_backward_navigation(self):
        state = {
            "workflow_status": "error",
            "navigation": {
                "current_phase": "plan",
                "direction": "backward",
                "target_phase": "context",
            },
        }
        assert route_after_phase(state) == END

    @pytest.mark.parametrize("phase", PHASE_ORDER)
    def test_error_halts_at_any_phase(self, phase):
        state = {
            "workflow_status": "error",
            "navigation": {"current_phase": phase, "direction": "forward"},
        }
        assert route_after_phase(state) == END


# ── Phase node error handling ────────────────────────────────────


class TestPhaseNodeErrorHandling:
    """Tests that phase nodes catch exceptions and set state.error (Req 19.1)."""

    @pytest.mark.asyncio
    async def test_research_phase_catches_llm_failure(self):
        state = {
            "context": {"spec_name": "Test", "user_explanation": "test"},
            "completed_phases": {"context": True},
        }
        app_context = MagicMock()
        app_context.llm = MagicMock()
        app_context.graph_store = MagicMock()

        with patch(
            "graph_kb_api.flows.v3.nodes.spec_phases.run_research",
            side_effect=RuntimeError("LLM service unavailable"),
        ):
            result = await research_phase(state, app_context)

        assert result["error"]["phase"] == "research"
        assert "LLM service unavailable" in result["error"]["message"]
        assert result["error"]["code"] == "PHASE_EXECUTION_ERROR"
        assert result["workflow_status"] == "error"

    @pytest.mark.asyncio
    async def test_plan_phase_catches_llm_failure(self):
        state = {
            "context": {"spec_name": "Test"},
            "research": {"approved": True},
        }
        app_context = MagicMock()
        app_context.llm = MagicMock()

        with patch(
            "graph_kb_api.flows.v3.nodes.spec_phases.run_plan",
            side_effect=ConnectionError("API connection lost"),
        ):
            result = await plan_phase(state, app_context)

        assert result["error"]["phase"] == "plan"
        assert "API connection lost" in result["error"]["message"]
        assert result["workflow_status"] == "error"

    @pytest.mark.asyncio
    async def test_decompose_phase_catches_llm_failure(self):
        state = {
            "context": {"spec_name": "Test"},
            "plan": {"approved": True},
        }
        app_context = MagicMock()
        app_context.llm = MagicMock()

        with patch(
            "graph_kb_api.flows.v3.nodes.spec_phases.run_decompose",
            side_effect=TimeoutError("Request timed out"),
        ):
            result = await decompose_phase(state, app_context)

        assert result["error"]["phase"] == "decompose"
        assert "Request timed out" in result["error"]["message"]
        assert result["workflow_status"] == "error"

    @pytest.mark.asyncio
    async def test_generate_phase_catches_llm_failure(self):
        state = {
            "context": {"spec_name": "Test"},
            "research": {"approved": True},
            "plan": {"approved": True},
            "decompose": {"stories": [{"id": "s1"}], "approved": True},
            "completed_phases": {
                "context": True,
                "research": True,
                "plan": True,
                "decompose": True,
            },
        }
        app_context = MagicMock()
        app_context.llm = MagicMock()

        with patch(
            "graph_kb_api.flows.v3.nodes.spec_phases.run_generate",
            side_effect=RuntimeError("Token limit exceeded"),
        ):
            result = await generate_phase(state, app_context)

        assert result["error"]["phase"] == "generate"
        assert "Token limit exceeded" in result["error"]["message"]
        assert result["workflow_status"] == "error"


# ── Phase node success clears error ─────────────────────────────


class TestPhaseNodeSuccessClearsError:
    """Tests that successful phase completion clears previous error (Req 19.2)."""

    @pytest.mark.asyncio
    async def test_research_success_clears_error(self):
        state = {
            "context": {"spec_name": "Test", "user_explanation": "test"},
            "completed_phases": {"context": True},
            "error": {"phase": "research", "message": "old", "code": "ERR"},
        }
        app_context = MagicMock()
        app_context.llm = MagicMock()
        app_context.graph_store = MagicMock()

        mock_findings = {
            "codebase": {},
            "documents": {},
            "risks": [],
            "gaps": [],
            "summary": "test",
            "confidence_score": 0.8,
        }

        with (
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.run_research",
                return_value=mock_findings,
            ),
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.interrupt",
                return_value={"approved": True, "feedback": ""},
            ),
        ):
            result = await research_phase(state, app_context)

        assert result["error"] == {}
        assert result["workflow_status"] == "running"
        assert result["completed_phases"]["research"] is True


# ── Engine retry_phase ───────────────────────────────────────────


class TestEngineRetryPhase:
    """Tests for UnifiedSpecEngine.retry_phase (Req 19.1, 19.2)."""

    def _make_engine(self):
        engine = UnifiedSpecEngine.__new__(UnifiedSpecEngine)
        engine._mode = "wizard"
        engine._progress_callback = None
        engine._app_context = MagicMock()
        engine.compiled_workflow = MagicMock()
        return engine

    @pytest.mark.asyncio
    async def test_retry_raises_when_no_checkpoint(self):
        engine = self._make_engine()
        engine.get_workflow_state = MagicMock(return_value=None)
        config = {"configurable": {"thread_id": "test-1"}}
        with pytest.raises(ValueError, match="No checkpoint found"):
            await engine.retry_phase(config)

    @pytest.mark.asyncio
    async def test_retry_raises_when_no_error(self):
        engine = self._make_engine()
        engine.get_workflow_state = MagicMock(
            return_value={"workflow_status": "running"}
        )
        config = {"configurable": {"thread_id": "test-1"}}
        with pytest.raises(ValueError, match="No error state to retry"):
            await engine.retry_phase(config)

    @pytest.mark.asyncio
    async def test_retry_clears_error_and_reinvokes(self):
        engine = self._make_engine()
        engine.get_workflow_state = MagicMock(
            return_value={
                "error": {"phase": "research", "message": "fail", "code": "ERR"},
                "workflow_status": "error",
            }
        )
        engine.compiled_workflow.update_state = MagicMock()
        engine.compiled_workflow.ainvoke = AsyncMock(
            return_value={"research": {"findings": {}}}
        )
        config = {"configurable": {"thread_id": "test-1"}}
        result = await engine.retry_phase(config)

        engine.compiled_workflow.update_state.assert_called_once_with(
            config,
            {"error": {}, "workflow_status": "running"},
            as_node="research",
        )
        engine.compiled_workflow.ainvoke.assert_called_once_with(None, config=config)
        assert result == {"research": {"findings": {}}}


# ── Dispatcher error detection and emission ──────────────────────


class TestDispatcherErrorDetection:
    """Tests for _check_and_emit_error in the dispatcher (Req 19.1)."""

    @pytest.mark.asyncio
    async def test_detects_error_and_emits(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _check_and_emit_error,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            result = {
                "error": {
                    "phase": "research",
                    "message": "LLM timeout",
                    "code": "PHASE_EXECUTION_ERROR",
                }
            }
            detected = await _check_and_emit_error(result, "c1", "w1", "s1")
            assert detected is True
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "PHASE_EXECUTION_ERROR"
            assert kw["data"]["phase"] == "research"

    @pytest.mark.asyncio
    async def test_no_error_returns_false(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _check_and_emit_error,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            detected = await _check_and_emit_error({"research": {}}, "c1", "w1", "s1")
            assert detected is False
            mock_mgr.send_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_error_dict_returns_false(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _check_and_emit_error,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            detected = await _check_and_emit_error({"error": {}}, "c1", "w1", "s1")
            assert detected is False
            mock_mgr.send_event.assert_not_called()


# ── Dispatcher resume with error state ───────────────────────────


class TestDispatcherResumeWithError:
    """Tests for handle_v3_spec_resume error recovery (Req 19.2, 19.4)."""

    @pytest.mark.asyncio
    async def test_resume_error_state_emits_prompt(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _register_session,
            handle_v3_spec_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_resumable_state = MagicMock(
            return_value={
                "phase": "research",
                "phase_data": {"findings": {"partial": True}},
                "completed_phases": {"context": True, "research": False},
                "workflow_status": "error",
                "error": {"phase": "research", "message": "timeout", "code": "ERR"},
                "state": {
                    "error": {"phase": "research", "message": "timeout", "code": "ERR"},
                    "navigation": {"current_phase": "research"},
                    "research": {"findings": {"partial": True}},
                },
            }
        )
        config = {"configurable": {"thread_id": "spec-se1"}}
        _register_session("se1", mock_engine, config, "c1", "w1")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("c1", "w1", {"session_id": "se1"})
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.phase.prompt"
            assert kw["data"]["phase"] == "research"
            assert kw["data"]["prefilled"] == {"findings": {"partial": True}}

    @pytest.mark.asyncio
    async def test_resume_normal_state_emits_prompt(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _register_session,
            handle_v3_spec_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_resumable_state = MagicMock(
            return_value={
                "phase": "plan",
                "phase_data": {"roadmap": {"phases": ["p1"]}},
                "completed_phases": {"context": True, "research": True, "plan": False},
                "workflow_status": "running",
                "error": {},
                "state": {
                    "navigation": {"current_phase": "plan"},
                    "plan": {"roadmap": {"phases": ["p1"]}},
                },
            }
        )
        config = {"configurable": {"thread_id": "spec-se2"}}
        _register_session("se2", mock_engine, config, "c1", "w1")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_resume("c1", "w1", {"session_id": "se2"})
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.phase.prompt"
            assert kw["data"]["phase"] == "plan"


# ── Dispatcher retry handler ─────────────────────────────────────


class TestDispatcherRetryHandler:
    """Tests for handle_v3_spec_retry (Req 19.1, 19.2)."""

    @pytest.mark.asyncio
    async def test_retry_missing_session_id_emits_error(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            handle_v3_spec_retry,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_retry("c1", "w1", {})
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_retry_session_not_found_emits_error(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            handle_v3_spec_retry,
        )

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_retry("c1", "w1", {"session_id": "nonexistent"})
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_retry_no_error_state_emits_retry_error(self):
        from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
            _register_session,
            handle_v3_spec_retry,
        )

        mock_engine = MagicMock()
        mock_engine.retry_phase = AsyncMock(
            side_effect=ValueError("No error state to retry")
        )
        config = {"configurable": {"thread_id": "spec-se3"}}
        _register_session("se3", mock_engine, config, "c1", "w1")

        with patch(
            "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager"
        ) as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_v3_spec_retry("c1", "w1", {"session_id": "se3"})
            kw = mock_mgr.send_event.call_args[1]
            assert kw["event_type"] == "spec.error"
            assert kw["data"]["code"] == "RETRY_ERROR"
