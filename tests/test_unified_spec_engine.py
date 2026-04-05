"""
Unit tests for UnifiedSpecEngine.

Covers:
- route_after_phase routing logic (7-phase DAG)
- PHASE_CASCADE / get_cascade_warning
- _build_initial_state defaults
- _compile_workflow produces a valid compiled graph
- reset_to_phase invalidation logic
- review→context loop-back
- completeness→orchestrate loop-back
"""

from __future__ import annotations

import pytest

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    route_after_phase,
)

# ── route_after_phase ────────────────────────────────────────────


class TestRouteAfterPhase:
    """Tests for the single routing function (Req 5.1–5.4)."""

    @pytest.mark.parametrize(
        "current, expected_next",
        [
            ("context", "review"),
            ("review", "research"),
            ("research", "plan"),
            ("plan", "orchestrate"),
            ("orchestrate", "completeness"),
            ("completeness", "generate"),
        ],
    )
    def test_forward_linear_progression(self, current, expected_next):
        state = {"navigation": {"current_phase": current, "direction": "forward"}}
        assert route_after_phase(state) == expected_next

    def test_forward_from_generate_returns_end(self):
        state = {"navigation": {"current_phase": "generate", "direction": "forward"}}
        assert route_after_phase(state) == "__end__"

    @pytest.mark.parametrize("target", PHASE_ORDER)
    def test_backward_returns_target(self, target):
        state = {
            "navigation": {
                "current_phase": "generate",
                "direction": "backward",
                "target_phase": target,
            }
        }
        assert route_after_phase(state) == target

    def test_backward_without_target_stays_at_current(self):
        state = {
            "navigation": {
                "current_phase": "plan",
                "direction": "backward",
            }
        }
        # No target_phase → fallback to current
        assert route_after_phase(state) == "plan"

    def test_missing_navigation_defaults_to_context(self):
        state = {}
        # No navigation → defaults to forward from context
        assert route_after_phase(state) == "review"

    def test_invalid_current_phase_defaults_to_context(self):
        state = {"navigation": {"current_phase": "invalid", "direction": "forward"}}
        assert route_after_phase(state) == "context"

    def test_review_loops_back_to_context_on_add_context(self):
        state = {
            "navigation": {"current_phase": "review", "direction": "forward"},
            "review": {"user_decision": "add_context"},
            "review_loop_count": 0,
        }
        assert route_after_phase(state) == "context"

    def test_review_does_not_loop_back_at_max(self):
        state = {
            "navigation": {"current_phase": "review", "direction": "forward"},
            "review": {"user_decision": "add_context"},
            "review_loop_count": 5,
        }
        assert route_after_phase(state) == "research"

    def test_completeness_loops_back_to_orchestrate_on_gaps(self):
        state = {
            "navigation": {
                "current_phase": "completeness",
                "direction": "forward",
            },
            "completeness": {"gaps_found": True},
            "completeness_loop_count": 0,
        }
        assert route_after_phase(state) == "orchestrate"

    def test_completeness_does_not_loop_back_at_max(self):
        state = {
            "navigation": {
                "current_phase": "completeness",
                "direction": "forward",
            },
            "completeness": {"gaps_found": True},
            "completeness_loop_count": 1,
        }
        assert route_after_phase(state) == "generate"

    def test_error_state_returns_end(self):
        state = {
            "workflow_status": "error",
            "navigation": {"current_phase": "research", "direction": "forward"},
        }
        assert route_after_phase(state) == "__end__"


# ── PHASE_CASCADE / get_cascade_warning ──────────────────────────


class TestCascade:
    """Tests for cascade map and get_cascade_warning (Req 6.1–6.6)."""

    def test_cascade_map_has_7_entries(self):
        assert len(PHASE_CASCADE) == 7

    def test_cascade_context_affects_all_downstream(self):
        assert PHASE_CASCADE["context"] == [
            "review",
            "research",
            "plan",
            "orchestrate",
            "completeness",
            "generate",
        ]

    def test_cascade_generate_affects_nothing(self):
        assert PHASE_CASCADE["generate"] == []

    def test_cascade_each_phase_only_lists_downstream(self):
        for i, phase in enumerate(PHASE_ORDER):
            expected = PHASE_ORDER[i + 1 :]
            assert PHASE_CASCADE[phase] == expected


# ── Engine instantiation & compilation ───────────────────────────


class TestEngineCompilation:
    """Tests for engine init and DAG compilation."""

    def _make_engine(self, mode="wizard"):
        """Create an engine with mocked dependencies."""
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        app_context.graph_store = MagicMock()

        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            mode=mode,
            progress_callback=None,
        )
        return engine

    def test_compiled_workflow_exists(self):
        engine = self._make_engine()
        assert engine.compiled_workflow is not None

    def test_wizard_mode_stored(self):
        engine = self._make_engine(mode="wizard")
        assert engine._mode == "wizard"

    def test_quick_mode_stored(self):
        engine = self._make_engine(mode="quick")
        assert engine._mode == "quick"

    def test_no_tools(self):
        engine = self._make_engine()
        assert engine.tools == []


# ── _build_initial_state ─────────────────────────────────────────


class TestBuildInitialState:
    """Tests for default state construction."""

    def _make_engine(self):
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        return UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            mode="wizard",
        )

    def test_defaults_filled(self):
        engine = self._make_engine()
        state = engine._build_initial_state({})
        assert state["mode"] == "wizard"
        assert state["workflow_status"] == "running"
        assert state["navigation"]["current_phase"] == "context"
        assert state["navigation"]["direction"] == "forward"
        assert all(v is False for v in state["completed_phases"].values())
        assert state["messages"] == []
        # Verify all 7 phases are in completed_phases
        for phase in PHASE_ORDER:
            assert phase in state["completed_phases"]

    def test_seed_overrides_defaults(self):
        engine = self._make_engine()
        state = engine._build_initial_state(
            {
                "context": {"spec_name": "My Feature"},
                "mode": "quick",
                "session_id": "sess-123",
            }
        )
        assert state["context"] == {"spec_name": "My Feature"}
        assert state["mode"] == "quick"
        assert state["session_id"] == "sess-123"

    def test_session_id_omitted_when_not_in_seed(self):
        engine = self._make_engine()
        state = engine._build_initial_state({})
        assert "session_id" not in state

    def test_all_7_phase_data_dicts_present(self):
        engine = self._make_engine()
        state = engine._build_initial_state({})
        for phase in PHASE_ORDER:
            assert phase in state, f"Missing phase data dict: {phase}"
            assert isinstance(state[phase], dict)


# ── get_cascade_warning (engine method) ──────────────────────────


class TestGetCascadeWarning:
    """Tests for the engine's get_cascade_warning method."""

    def _make_engine(self):
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        return UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
        )

    def test_context_cascade_warning(self):
        engine = self._make_engine()
        warning = engine.get_cascade_warning("context")
        assert warning["target_phase"] == "context"
        assert warning["affected_phases"] == [
            "review",
            "research",
            "plan",
            "orchestrate",
            "completeness",
            "generate",
        ]

    def test_generate_cascade_warning_empty(self):
        engine = self._make_engine()
        warning = engine.get_cascade_warning("generate")
        assert warning["affected_phases"] == []

    def test_unknown_phase_returns_empty(self):
        engine = self._make_engine()
        warning = engine.get_cascade_warning("nonexistent")
        assert warning["affected_phases"] == []

    def test_orchestrate_cascade_warning(self):
        engine = self._make_engine()
        warning = engine.get_cascade_warning("orchestrate")
        assert warning["affected_phases"] == ["completeness", "generate"]


# ── reset_to_phase ───────────────────────────────────────────────


class TestResetToPhase:
    """Tests for reset_to_phase cascade invalidation."""

    def _make_engine(self):
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        return UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
        )

    @pytest.mark.asyncio
    async def test_invalid_target_phase_raises(self):
        engine = self._make_engine()
        config = {"configurable": {"thread_id": "test-thread"}}
        with pytest.raises(ValueError, match="Invalid target_phase"):
            await engine.reset_to_phase("nonexistent", config)

    @pytest.mark.asyncio
    async def test_no_checkpoint_raises(self):
        engine = self._make_engine()
        # Mock get_workflow_state to return None (no checkpoint)
        engine.get_workflow_state = MagicMock(return_value=None)
        config = {"configurable": {"thread_id": "test-thread"}}
        with pytest.raises(ValueError, match="No checkpoint found"):
            await engine.reset_to_phase("context", config)

    @pytest.mark.asyncio
    async def test_decompose_is_invalid_target(self):
        """decompose is no longer a valid phase in the 7-phase DAG."""
        engine = self._make_engine()
        config = {"configurable": {"thread_id": "test-thread"}}
        with pytest.raises(ValueError, match="Invalid target_phase"):
            await engine.reset_to_phase("decompose", config)


# ── _emit_progress ───────────────────────────────────────────────


class TestEmitProgress:
    """Tests for progress callback invocation."""

    @pytest.mark.asyncio
    async def test_sync_callback_invoked(self):
        callback = MagicMock()
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            progress_callback=callback,
        )
        await engine._emit_progress({"phase": "research", "percent": 0.5})
        callback.assert_called_once_with({"phase": "research", "percent": 0.5})

    @pytest.mark.asyncio
    async def test_async_callback_invoked(self):
        callback = AsyncMock()
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            progress_callback=callback,
        )
        await engine._emit_progress({"phase": "plan", "percent": 0.8})
        callback.assert_awaited_once_with({"phase": "plan", "percent": 0.8})

    @pytest.mark.asyncio
    async def test_no_callback_does_not_raise(self):
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            progress_callback=None,
        )
        # Should not raise
        await engine._emit_progress({"phase": "context"})

    @pytest.mark.asyncio
    async def test_failing_callback_does_not_raise(self):
        callback = MagicMock(side_effect=RuntimeError("boom"))
        llm = MagicMock()
        app_context = MagicMock()
        app_context.llm = llm
        engine = UnifiedSpecEngine(
            llm=llm,
            app_context=app_context,
            checkpointer=None,
            progress_callback=callback,
        )
        # Should swallow the error
        await engine._emit_progress({"phase": "research"})
