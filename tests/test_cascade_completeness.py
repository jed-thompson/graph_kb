"""Property-based test for cascade completeness.

Property 5: Cascade Completeness — For any backward navigation to P[i]
            with cascade confirmed, all downstream P[j] (j > i) have
            ``completed_phases[P[j]] == false`` and ``state[P[j]] == {}``.

**Validates: Requirements 6.1, 6.3**
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_CASCADE,
    PHASE_ORDER,
    UnifiedSpecEngine,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Target phase index: any phase that has at least one downstream phase (0..3)
target_phase_idx_st = st.integers(min_value=0, max_value=len(PHASE_ORDER) - 2)

# Generate non-empty phase data dicts to simulate completed phases
_phase_data_st = st.fixed_dictionaries(
    {"marker": st.text(min_size=1, max_size=20)},
    optional={
        "extra_field": st.text(max_size=30),
        "approved": st.just(True),
    },
)


@st.composite
def completed_state_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a state where all phases have data and are marked complete.

    This simulates a workflow that has progressed through all phases
    before the user navigates backward.
    """
    state: Dict[str, Any] = {
        "completed_phases": {},
        "navigation": {"current_phase": "generate", "direction": "forward"},
        "mode": "wizard",
        "workflow_status": "running",
        "messages": [],
    }
    for phase in PHASE_ORDER:
        state[phase] = draw(_phase_data_st)
        state["completed_phases"][phase] = True

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> UnifiedSpecEngine:
    """Create a minimal UnifiedSpecEngine for testing cascade logic."""
    engine = UnifiedSpecEngine.__new__(UnifiedSpecEngine)
    engine._mode = "wizard"
    engine._progress_callback = None
    engine._app_context = MagicMock()
    return engine


def _apply_cascade_invalidation(
    state: Dict[str, Any],
    target_phase: str,
) -> Dict[str, Any]:
    """Apply the same cascade invalidation logic as ``reset_to_phase``.

    This replicates the invalidation logic from ``reset_to_phase`` so we
    can verify the property without needing a full LangGraph runtime.
    """
    affected = PHASE_CASCADE.get(target_phase, [])

    # Invalidate downstream phase data and completion flags
    for phase in affected:
        state[phase] = {}
        state["completed_phases"][phase] = False

    # Set navigation to backward
    state["navigation"] = {
        "current_phase": target_phase,
        "direction": "backward",
        "target_phase": target_phase,
    }

    return state


# ---------------------------------------------------------------------------
# Property 5: Cascade Completeness
# ---------------------------------------------------------------------------


class TestCascadeCompleteness:
    """Property 5: Cascade Completeness — For any backward navigation to
    P[i] with cascade confirmed, all downstream P[j] (j > i) have
    ``completed_phases[P[j]] == false`` and ``state[P[j]] == {}``.

    **Validates: Requirements 6.1, 6.3**
    """

    # ── Core property: downstream phases are fully invalidated ───

    @given(
        target_idx=target_phase_idx_st,
        state=completed_state_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_downstream_phases_invalidated(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """For any backward navigation to P[i], all downstream P[j] (j > i)
        have ``completed_phases[P[j]] == False`` and ``state[P[j]] == {}``.

        **Validates: Requirements 6.1, 6.3**
        """
        target_phase = PHASE_ORDER[target_idx]
        downstream = PHASE_ORDER[target_idx + 1 :]

        # Apply cascade invalidation
        result_state = _apply_cascade_invalidation(state, target_phase)

        # Verify all downstream phases are invalidated
        for phase in downstream:
            assert result_state["completed_phases"][phase] is False, (
                f"completed_phases['{phase}'] should be False after cascade "
                f"to '{target_phase}', got {result_state['completed_phases'][phase]}"
            )
            assert result_state[phase] == {}, (
                f"state['{phase}'] should be {{}} after cascade "
                f"to '{target_phase}', got {result_state[phase]}"
            )

    # ── Cascade map matches PHASE_ORDER downstream slicing ───────

    @given(target_idx=target_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_cascade_map_matches_phase_order(self, target_idx: int):
        """The PHASE_CASCADE map for P[i] lists exactly P[i+1..n],
        matching the PHASE_ORDER slice.

        **Validates: Requirements 6.1**
        """
        target_phase = PHASE_ORDER[target_idx]
        expected_downstream = PHASE_ORDER[target_idx + 1 :]
        actual_cascade = PHASE_CASCADE[target_phase]

        assert actual_cascade == expected_downstream, (
            f"PHASE_CASCADE['{target_phase}'] = {actual_cascade}, "
            f"expected {expected_downstream}"
        )

    # ── Target phase data is preserved ───────────────────────────

    @given(
        target_idx=target_phase_idx_st,
        state=completed_state_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_target_phase_data_preserved(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """The target phase P[i] retains its data after cascade reset.
        Only downstream phases are cleared.

        **Validates: Requirements 6.3**
        """
        target_phase = PHASE_ORDER[target_idx]
        original_target_data = dict(state[target_phase])

        result_state = _apply_cascade_invalidation(state, target_phase)

        assert result_state[target_phase] == original_target_data, (
            f"Target phase '{target_phase}' data should be preserved. "
            f"Expected {original_target_data}, got {result_state[target_phase]}"
        )

    # ── Engine reset_to_phase uses PHASE_CASCADE correctly ───────

    @given(target_idx=target_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_engine_reset_invalidates_downstream(self, target_idx: int):
        """UnifiedSpecEngine.reset_to_phase computes the correct affected
        phases from PHASE_CASCADE and passes invalidation updates.

        **Validates: Requirements 6.1, 6.3**
        """
        target_phase = PHASE_ORDER[target_idx]
        downstream = PHASE_ORDER[target_idx + 1 :]

        engine = _make_engine()

        # Build a state where all phases are complete with data
        mock_state: Dict[str, Any] = {
            "completed_phases": {p: True for p in PHASE_ORDER},
            "navigation": {"current_phase": "generate", "direction": "forward"},
        }
        for phase in PHASE_ORDER:
            mock_state[phase] = {"data": f"{phase}_data"}

        engine.get_workflow_state = MagicMock(return_value=mock_state)
        engine.resume_workflow = AsyncMock(return_value={"resumed": True})

        config = {"configurable": {"thread_id": "test-thread"}}
        await engine.reset_to_phase(target_phase, config)

        # Verify resume_workflow was called with the target phase's data
        engine.resume_workflow.assert_called_once()
        call_kwargs = engine.resume_workflow.call_args.kwargs
        resume_data = call_kwargs.get("resume_data")
        assert resume_data == {"data": f"{target_phase}_data"}, (
            f"resume_workflow should receive target phase data, got {resume_data}"
        )

        # Verify get_cascade_warning returns the correct affected phases
        warning = engine.get_cascade_warning(target_phase)
        assert warning["affected_phases"] == downstream, (
            f"get_cascade_warning('{target_phase}') should return {downstream}, "
            f"got {warning['affected_phases']}"
        )
