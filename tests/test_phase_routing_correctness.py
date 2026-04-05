"""Property-based test for phase routing correctness.

Property 4: Phase Routing Correctness — For any valid state with
            ``current_phase = P[i]``: forward with ``i < 4`` returns
            ``P[i+1]``; backward with valid target returns that target;
            ``i = 4`` forward returns ``END``.

**Validates: Requirements 5.1, 5.2, 5.3, 3.9**
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st
from langgraph.graph import END

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    route_after_phase,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Index for phases that have a successor (0..3 inclusive)
forward_phase_idx_st = st.integers(min_value=0, max_value=len(PHASE_ORDER) - 2)

# Index for the last phase (generate, index 4)
last_phase_idx_st = st.just(len(PHASE_ORDER) - 1)

# Any valid phase index
any_phase_idx_st = st.integers(min_value=0, max_value=len(PHASE_ORDER) - 1)


@st.composite
def backward_nav_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a state with backward navigation and a valid target phase.

    The target must be a valid phase (any phase in PHASE_ORDER).
    """
    current_idx = draw(st.integers(min_value=0, max_value=len(PHASE_ORDER) - 1))
    # Target can be any valid phase for backward navigation
    target_idx = draw(st.integers(min_value=0, max_value=len(PHASE_ORDER) - 1))
    return {
        "navigation": {
            "current_phase": PHASE_ORDER[current_idx],
            "direction": "backward",
            "target_phase": PHASE_ORDER[target_idx],
        }
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_forward_state(phase_idx: int) -> Dict[str, Any]:
    """Build a minimal state dict for forward navigation at the given phase index."""
    return {
        "navigation": {
            "current_phase": PHASE_ORDER[phase_idx],
            "direction": "forward",
        }
    }


# ---------------------------------------------------------------------------
# Property 4: Phase Routing Correctness
# ---------------------------------------------------------------------------


class TestPhaseRoutingCorrectness:
    """Property 4: Phase Routing Correctness — For any valid state with
    ``current_phase = P[i]``: forward with ``i < 4`` returns ``P[i+1]``;
    backward with valid target returns that target; ``i = 4`` forward
    returns ``END``.

    **Validates: Requirements 5.1, 5.2, 5.3, 3.9**
    """

    # ── Forward: P[i] with i < 4 → P[i+1] ───────────────────────

    @given(idx=forward_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_forward_returns_next_phase(self, idx: int):
        """For any phase P[i] where i < 4, forward navigation returns P[i+1].

        **Validates: Requirements 5.1**
        """
        state = _make_forward_state(idx)
        result = route_after_phase(state)
        assert result == PHASE_ORDER[idx + 1], (
            f"Expected {PHASE_ORDER[idx + 1]} after {PHASE_ORDER[idx]}, got {result}"
        )

    # ── Forward: generate (i=4) → END ────────────────────────────

    @given(idx=last_phase_idx_st)
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
    def test_generate_forward_returns_end(self, idx: int):
        """For generate (i=4) forward, returns END (LangGraph's ``__end__``).

        **Validates: Requirements 5.3**
        """
        state = _make_forward_state(idx)
        result = route_after_phase(state)
        assert result == END, (
            f"Expected END ({END!r}) for generate forward, got {result!r}"
        )

    # ── Backward: valid target → that target ─────────────────────

    @given(data=backward_nav_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_backward_returns_target_phase(self, data: Dict[str, Any]):
        """For backward navigation with a valid target, returns that target.

        **Validates: Requirements 5.2**
        """
        expected_target = data["navigation"]["target_phase"]
        result = route_after_phase(data)
        assert result == expected_target, (
            f"Expected backward target {expected_target!r}, got {result!r}"
        )
