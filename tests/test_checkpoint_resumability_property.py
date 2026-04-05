"""Property-based test for checkpoint resumability round-trip.

Property 11: Checkpoint Resumability Round-Trip — For any session with
             ``workflow_status != "completed"``, checkpointing and then
             ``resume_workflow`` restores the session to the exact phase
             and data state at the last checkpoint.

**Validates: Requirements 23.1, 4.7**
"""

from __future__ import annotations

import copy
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    UnifiedSpecEngine,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-completed workflow statuses (completed sessions cannot be resumed)
_resumable_status_st = st.sampled_from(["idle", "running", "paused", "error"])

# Phase index (0..4)
_phase_idx_st = st.integers(min_value=0, max_value=len(PHASE_ORDER) - 1)

# Generate non-empty phase data with arbitrary keys
_phase_data_st = st.fixed_dictionaries(
    {"marker": st.text(min_size=1, max_size=30)},
    optional={
        "extra": st.text(max_size=20),
        "approved": st.booleans(),
        "findings": st.fixed_dictionaries(
            {"summary": st.text(min_size=1, max_size=40)}
        ),
    },
)

# Generate optional error info for error-status sessions
_error_info_st = st.fixed_dictionaries(
    {
        "phase": st.sampled_from(PHASE_ORDER),
        "message": st.text(min_size=1, max_size=60),
        "code": st.sampled_from(
            ["PHASE_EXECUTION_ERROR", "TIMEOUT", "LLM_ERROR", "TOOL_ERROR"]
        ),
    }
)

# Thread ID strategy
_thread_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=3,
    max_size=30,
).map(lambda s: f"spec-{s}")


@st.composite
def resumable_session_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate an arbitrary non-completed session state with phase data.

    The generated state has:
    - A random current phase
    - A resumable workflow_status (not "completed")
    - Completed phases up to (but not including) the current phase
    - Non-empty data for completed phases and partial data for current phase
    - Optional error info when status is "error"
    """
    phase_idx = draw(_phase_idx_st)
    current_phase = PHASE_ORDER[phase_idx]
    status = draw(_resumable_status_st)

    # Build completed_phases: all before current are True, rest False
    completed_phases = {}
    for i, p in enumerate(PHASE_ORDER):
        completed_phases[p] = i < phase_idx

    # Build phase data: completed phases get data, current gets partial data
    phase_data = {}
    for i, p in enumerate(PHASE_ORDER):
        if i < phase_idx:
            phase_data[p] = draw(_phase_data_st)
        elif i == phase_idx:
            # Current phase may have partial data
            phase_data[p] = draw(st.one_of(st.just({}), _phase_data_st))
        else:
            phase_data[p] = {}

    state: Dict[str, Any] = {
        "navigation": {
            "current_phase": current_phase,
            "direction": "forward",
        },
        "context": phase_data.get("context", {}),
        "research": phase_data.get("research", {}),
        "plan": phase_data.get("plan", {}),
        "decompose": phase_data.get("decompose", {}),
        "generate": phase_data.get("generate", {}),
        "mode": "wizard",
        "workflow_status": status,
        "completed_phases": completed_phases,
        "messages": [],
    }

    # Add error info for error-status sessions
    if status == "error":
        error = draw(_error_info_st)
        # Error phase should match current phase for consistency
        error["phase"] = current_phase
        state["error"] = error

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Property 11: Checkpoint Resumability Round-Trip
# ---------------------------------------------------------------------------


class TestCheckpointResumabilityRoundTrip:
    """Property 11: Checkpoint Resumability Round-Trip — For any session
    with ``workflow_status != "completed"``, checkpointing and then
    ``resume_workflow`` restores the session to the exact phase and data
    state at the last checkpoint.

    **Validates: Requirements 23.1, 4.7**
    """

    # ── Core property: get_resumable_state returns exact checkpoint data ──

    @given(
        session_state=resumable_session_st(),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_resumable_state_matches_checkpoint_phase_and_data(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any non-completed session, get_resumable_state returns the
        exact current phase and phase data from the checkpoint.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None, "Non-completed session must be resumable"

        # Determine expected phase
        error_info = session_state.get("error")
        if error_info and isinstance(error_info, dict) and error_info.get("phase"):
            expected_phase = error_info["phase"]
        else:
            expected_phase = session_state["navigation"]["current_phase"]

        # Phase must match
        assert result["phase"] == expected_phase, (
            f"Expected phase '{expected_phase}', got '{result['phase']}'"
        )

        # Phase data must match exactly
        expected_data = session_state.get(expected_phase, {})
        assert result["phase_data"] == expected_data, (
            f"Phase data mismatch for '{expected_phase}': "
            f"expected {expected_data}, got {result['phase_data']}"
        )

    # ── Property: completed_phases preserved exactly ──

    @given(
        session_state=resumable_session_st(),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_resumable_state_preserves_completed_phases(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any non-completed session, get_resumable_state returns the
        exact completed_phases map from the checkpoint.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["completed_phases"] == session_state["completed_phases"], (
            f"completed_phases mismatch: "
            f"expected {session_state['completed_phases']}, "
            f"got {result['completed_phases']}"
        )

    # ── Property: workflow_status preserved exactly ──

    @given(
        session_state=resumable_session_st(),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_resumable_state_preserves_workflow_status(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any non-completed session, get_resumable_state returns the
        exact workflow_status from the checkpoint.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None
        assert result["workflow_status"] == session_state["workflow_status"], (
            f"workflow_status mismatch: "
            f"expected '{session_state['workflow_status']}', "
            f"got '{result['workflow_status']}'"
        )

    # ── Property: error info preserved for error-state sessions ──

    @given(
        session_state=resumable_session_st().filter(
            lambda s: s["workflow_status"] == "error"
        ),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_resumable_state_preserves_error_info(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any error-state session, get_resumable_state returns the
        exact error dict from the checkpoint.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None
        expected_error = session_state.get("error", {})
        assert result["error"] == expected_error, (
            f"Error info mismatch: expected {expected_error}, got {result['error']}"
        )

    # ── Property: completed sessions are rejected (negative case) ──

    @given(
        phase_idx=_phase_idx_st,
        thread_id=_thread_id_st,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_completed_sessions_are_not_resumable(
        self,
        phase_idx: int,
        thread_id: str,
        data: st.DataObject,
    ):
        """For any session with workflow_status == "completed",
        get_resumable_state raises ValueError.

        **Validates: Requirements 23.1**
        """
        current_phase = PHASE_ORDER[phase_idx]
        phase_data = {}
        for i, p in enumerate(PHASE_ORDER):
            if i <= phase_idx:
                phase_data[p] = data.draw(_phase_data_st)
            else:
                phase_data[p] = {}

        state = {
            "navigation": {"current_phase": current_phase, "direction": "forward"},
            "context": phase_data.get("context", {}),
            "research": phase_data.get("research", {}),
            "plan": phase_data.get("plan", {}),
            "decompose": phase_data.get("decompose", {}),
            "generate": phase_data.get("generate", {}),
            "mode": "wizard",
            "workflow_status": "completed",
            "completed_phases": {p: True for p in PHASE_ORDER},
            "messages": [],
        }

        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=state)

        config = {"configurable": {"thread_id": thread_id}}
        with pytest.raises(ValueError, match="completed"):
            engine.get_resumable_state(config)

    # ── Property: full state snapshot is included for resume_workflow ──

    @given(
        session_state=resumable_session_st(),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_resumable_state_includes_full_snapshot(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any non-completed session, get_resumable_state includes the
        full state snapshot so resume_workflow can restore the exact state.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None
        assert "state" in result, "Resumable state must include full snapshot"

        # The full snapshot should contain all phase data
        full_state = result["state"]
        for phase in PHASE_ORDER:
            assert full_state.get(phase) == session_state.get(phase), (
                f"Full snapshot phase '{phase}' data mismatch: "
                f"expected {session_state.get(phase)}, "
                f"got {full_state.get(phase)}"
            )

    # ── Property: all upstream phase data preserved in round-trip ──

    @given(
        session_state=resumable_session_st(),
        thread_id=_thread_id_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_all_phase_data_preserved_in_round_trip(
        self,
        session_state: Dict[str, Any],
        thread_id: str,
    ):
        """For any non-completed session, every phase's data in the
        checkpoint is exactly preserved in the resumable state snapshot.

        **Validates: Requirements 23.1, 4.7**
        """
        engine = _make_engine()
        checkpoint = copy.deepcopy(session_state)
        engine.get_workflow_state = MagicMock(return_value=checkpoint)

        config = {"configurable": {"thread_id": thread_id}}
        result = engine.get_resumable_state(config)

        assert result is not None

        # Verify every phase's data is preserved
        for phase in PHASE_ORDER:
            original = session_state.get(phase, {})
            restored = result["state"].get(phase, {})
            assert restored == original, (
                f"Phase '{phase}' data not preserved in round-trip: "
                f"original={original}, restored={restored}"
            )

        # Verify completed_phases map is preserved
        assert result["completed_phases"] == session_state["completed_phases"]

        # Verify workflow_status is preserved
        assert result["workflow_status"] == session_state["workflow_status"]
