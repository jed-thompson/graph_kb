"""Property-based test for cascade preserves target phase data.

Property 7: Cascade Preserves Target Phase Data — For any backward
            navigation to P[i] with cascade confirmed, data for P[i]
            is preserved and pre-filled on resume.

**Validates: Requirements 6.4, 10.4**
"""

from __future__ import annotations

import copy
from typing import Any, Dict
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

# Any valid phase that has downstream phases (indices 0..3)
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
    """Create a minimal UnifiedSpecEngine for testing."""
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

    Replicates the invalidation from ``reset_to_phase`` so we can verify
    the property without needing a full LangGraph runtime.
    """
    affected = PHASE_CASCADE.get(target_phase, [])

    for phase in affected:
        state[phase] = {}
        state["completed_phases"][phase] = False

    state["navigation"] = {
        "current_phase": target_phase,
        "direction": "backward",
        "target_phase": target_phase,
    }

    return state


# ---------------------------------------------------------------------------
# Property 7: Cascade Preserves Target Phase Data
# ---------------------------------------------------------------------------


class TestCascadePreservesTargetPhaseData:
    """Property 7: Cascade Preserves Target Phase Data — For any backward
    navigation to P[i] with cascade confirmed, data for P[i] is preserved
    and pre-filled on resume.

    **Validates: Requirements 6.4, 10.4**
    """

    # ── 1. Target phase data is preserved after cascade ──────────

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
        """For any backward navigation to P[i] with cascade confirmed,
        the target phase P[i] retains its original data dict unchanged.

        **Validates: Requirements 6.4**
        """
        target_phase = PHASE_ORDER[target_idx]
        original_target_data = copy.deepcopy(state[target_phase])

        _apply_cascade_invalidation(state, target_phase)

        assert state[target_phase] == original_target_data, (
            f"Target phase '{target_phase}' data should be preserved after "
            f"cascade. Expected {original_target_data}, got {state[target_phase]}"
        )

    # ── 2. Downstream phase data is cleared ──────────────────────

    @given(
        target_idx=target_phase_idx_st,
        state=completed_state_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_downstream_data_cleared(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """For any backward navigation to P[i] with cascade confirmed,
        all downstream P[j] (j > i) have their data cleared to {}.

        **Validates: Requirements 6.4**
        """
        target_phase = PHASE_ORDER[target_idx]
        downstream = PHASE_ORDER[target_idx + 1 :]

        _apply_cascade_invalidation(state, target_phase)

        for phase in downstream:
            assert state[phase] == {}, (
                f"Downstream phase '{phase}' data should be cleared after "
                f"cascade to '{target_phase}', got {state[phase]}"
            )
            assert state["completed_phases"][phase] is False, (
                f"Downstream phase '{phase}' completed_phases should be False "
                f"after cascade to '{target_phase}', "
                f"got {state['completed_phases'][phase]}"
            )

    # ── 3. Target phase completion status preserved ──────────────

    @given(
        target_idx=target_phase_idx_st,
        state=completed_state_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_target_phase_completion_status_preserved(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """For any backward navigation to P[i] with cascade confirmed,
        the completion status of the target phase P[i] is preserved
        (remains True if it was True before the cascade).

        **Validates: Requirements 6.4**
        """
        target_phase = PHASE_ORDER[target_idx]
        original_completion = state["completed_phases"][target_phase]

        _apply_cascade_invalidation(state, target_phase)

        assert state["completed_phases"][target_phase] == original_completion, (
            f"Target phase '{target_phase}' completion status should be "
            f"preserved. Expected {original_completion}, "
            f"got {state['completed_phases'][target_phase]}"
        )

    # ── 4. Pre-fill data available on resume via engine ──────────

    @given(target_idx=target_phase_idx_st, state=completed_state_st())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_prefill_data_available_on_resume(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """When engine.reset_to_phase is called, resume_workflow receives
        the target phase's original data so it can be pre-filled on resume.

        **Validates: Requirements 6.4, 10.4**
        """
        target_phase = PHASE_ORDER[target_idx]
        original_target_data = copy.deepcopy(state[target_phase])

        engine = _make_engine()
        engine.get_workflow_state = MagicMock(return_value=copy.deepcopy(state))
        engine.resume_workflow = AsyncMock(return_value={"resumed": True})

        config = {"configurable": {"thread_id": "test-thread"}}
        await engine.reset_to_phase(target_phase, config)

        # resume_workflow must have been called with the target phase data
        engine.resume_workflow.assert_called_once()
        call_kwargs = engine.resume_workflow.call_args.kwargs
        resume_data = call_kwargs.get("resume_data")

        assert resume_data == original_target_data, (
            f"resume_workflow should receive target phase '{target_phase}' "
            f"data for pre-filling. Expected {original_target_data}, "
            f"got {resume_data}"
        )
