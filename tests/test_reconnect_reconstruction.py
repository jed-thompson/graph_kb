"""Property-based and unit tests for reconnect state reconstruction.

Tests the ``PlanDispatcher._reconstruct_phase_from_log()`` static method that
reconstructs the current phase, step, and progress from a transition log and
fingerprints dict during client reconnection.

**Validates: Requirements 17.1**
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

# ---------------------------------------------------------------------------
# Constants mirrored from PlanDispatcher for test assertions
# ---------------------------------------------------------------------------

_PHASE_ORDER = ("context", "research", "planning", "orchestrate", "assembly")

# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Valid phase names
phase_st = st.sampled_from(list(_PHASE_ORDER))

# Arbitrary step name (from_node value)
step_st = st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N", "Pd")))

# Timestamp-like string
timestamp_st = st.text(min_size=1, max_size=30)


@st.composite
def transition_entry_st(draw, phase=None):
    """Generate a single valid TransitionEntry dict."""
    return {
        "timestamp": draw(timestamp_st),
        "from_node": draw(step_st),
        "to_node": draw(step_st),
        "subgraph": phase or draw(phase_st),
        "reason": "step_complete",
        "budget_snapshot": {},
    }


@st.composite
def corrupted_entry_st(draw):
    """Generate a corrupted/invalid transition entry."""
    choice = draw(st.sampled_from(["string", "missing_subgraph", "none_subgraph", "int"]))
    if choice == "string":
        return draw(st.text(max_size=20))
    elif choice == "missing_subgraph":
        return {"timestamp": draw(timestamp_st), "from_node": draw(step_st)}
    elif choice == "none_subgraph":
        return {"timestamp": draw(timestamp_st), "from_node": draw(step_st), "subgraph": None}
    else:
        return draw(st.integers())


@st.composite
def transition_log_st(draw, min_size=1, max_size=10):
    """Generate a valid transition log (list of TransitionEntry dicts)."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(transition_entry_st()) for _ in range(size)]


@st.composite
def mixed_transition_log_st(draw, min_valid=1, max_size=10):
    """Generate a transition log with a mix of valid and corrupted entries,
    ensuring at least ``min_valid`` valid entries exist."""
    valid = [draw(transition_entry_st()) for _ in range(min_valid)]
    extra_count = draw(st.integers(min_value=0, max_value=max_size - min_valid))
    extras = [
        draw(st.one_of(transition_entry_st(), corrupted_entry_st()))
        for _ in range(extra_count)
    ]
    combined = valid + extras
    # Shuffle so valid entries aren't always first
    shuffled = draw(st.permutations(combined))
    return list(shuffled)


@st.composite
def fingerprints_st(draw):
    """Generate a random fingerprints dict (subset of phases marked complete)."""
    result: Dict[str, Any] = {}
    for phase in _PHASE_ORDER:
        if draw(st.booleans()):
            result[phase] = {
                "phase": phase,
                "input_hash": draw(st.text(min_size=3, max_size=10)),
                "output_refs": [],
                "completed_at": draw(timestamp_st),
            }
    return result


@st.composite
def completed_phases_st(draw):
    """Generate a random completed_phases dict."""
    result: Dict[str, bool] = {}
    for phase in _PHASE_ORDER:
        if draw(st.booleans()):
            result[phase] = True
    return result


# ---------------------------------------------------------------------------
# Property 13: Reconnect state reconstruction from transition log
# ---------------------------------------------------------------------------


class TestReconnectReconstructionProperty:
    """Feature: plan-feature-refactoring, Property 13: Reconnect state
    reconstruction from transition log

    **Validates: Requirements 17.1**
    """

    @given(
        log=transition_log_st(min_size=1, max_size=10),
        fingerprints=fingerprints_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_log_returns_valid_phase(
        self,
        log: List[Dict[str, Any]],
        fingerprints: Dict[str, Any],
    ):
        """For any valid transition log, the returned phase is either the last
        logged phase or the next phase after a fingerprinted phase, and is
        always a member of _PHASE_ORDER.

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        state = {"transition_log": log, "fingerprints": fingerprints}
        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        assert phase is not None, (
            f"Expected a non-None phase for a valid log. Log: {log!r}"
        )
        assert phase in _PHASE_ORDER, (
            f"Returned phase {phase!r} is not in _PHASE_ORDER. "
            f"Log: {log!r}, Fingerprints: {fingerprints!r}"
        )

    @given(
        log=transition_log_st(min_size=1, max_size=10),
        fingerprints=fingerprints_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_progress_in_valid_range_when_present(
        self,
        log: List[Dict[str, Any]],
        fingerprints: Dict[str, Any],
    ):
        """When progress is returned (not None), it must be in [0.0, 1.0].

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        state = {"transition_log": log, "fingerprints": fingerprints}
        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        if progress is not None:
            assert 0.0 <= progress <= 1.0, (
                f"Progress {progress} out of range [0.0, 1.0]. "
                f"Phase: {phase!r}, Step: {step!r}"
            )

    @given(
        log=transition_log_st(min_size=1, max_size=10),
        fingerprints=fingerprints_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_phase_is_last_logged_or_advanced_by_fingerprint(
        self,
        log: List[Dict[str, Any]],
        fingerprints: Dict[str, Any],
    ):
        """The returned phase is either the last valid logged phase or the next
        phase in _PHASE_ORDER when the logged phase has a fingerprint (meaning
        it was completed).

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        state = {"transition_log": log, "fingerprints": fingerprints}
        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        # Find the last valid entry's phase
        last_logged_phase = None
        for entry in reversed(log):
            if isinstance(entry, dict) and isinstance(entry.get("subgraph"), str):
                last_logged_phase = entry["subgraph"]
                break

        if last_logged_phase is None:
            # No valid entries — should return None
            assert phase is None
            return

        if last_logged_phase in fingerprints and last_logged_phase in _PHASE_ORDER:
            idx = _PHASE_ORDER.index(last_logged_phase)
            if idx < len(_PHASE_ORDER) - 1:
                # Should advance to next phase
                assert phase == _PHASE_ORDER[idx + 1], (
                    f"Expected phase to advance from {last_logged_phase!r} to "
                    f"{_PHASE_ORDER[idx + 1]!r}, got {phase!r}"
                )
                assert step is None
                assert progress == 0.0
            else:
                # Last phase (assembly) — cannot advance
                assert phase == last_logged_phase
        else:
            # No fingerprint — phase should be the last logged phase
            assert phase == last_logged_phase

    @given(data=st.data())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_or_corrupted_log_returns_safe_default(self, data):
        """For empty or fully corrupted transition logs, the function returns
        (None, None, None) as a safe fallback.

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        choice = data.draw(st.sampled_from(["empty", "none", "missing", "all_corrupted"]))

        if choice == "empty":
            state: Dict[str, Any] = {"transition_log": [], "fingerprints": {}}
        elif choice == "none":
            state = {"transition_log": None, "fingerprints": {}}
        elif choice == "missing":
            state = {"fingerprints": {}}
        else:
            # All corrupted entries
            corrupted = [data.draw(corrupted_entry_st()) for _ in range(data.draw(st.integers(min_value=1, max_value=5)))]
            state = {"transition_log": corrupted, "fingerprints": {}}

        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        assert phase is None, f"Expected None phase for {choice} log, got {phase!r}"
        assert step is None, f"Expected None step for {choice} log, got {step!r}"
        assert progress is None, f"Expected None progress for {choice} log, got {progress!r}"

    @given(
        log=mixed_transition_log_st(min_valid=1, max_size=8),
        fingerprints=fingerprints_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_corrupted_entries_skipped_gracefully(
        self,
        log: List[Any],
        fingerprints: Dict[str, Any],
    ):
        """When the log contains a mix of valid and corrupted entries, the
        function still returns a valid result by skipping corrupted entries.

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        state = {"transition_log": log, "fingerprints": fingerprints}
        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        # Since we guaranteed at least 1 valid entry, phase should not be None
        assert phase is not None, (
            f"Expected non-None phase with at least 1 valid entry. Log: {log!r}"
        )
        assert phase in _PHASE_ORDER

    @given(
        phase_name=phase_st,
        fingerprints=fingerprints_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_fingerprint_advancement_never_exceeds_phase_order(
        self,
        phase_name: str,
        fingerprints: Dict[str, Any],
    ):
        """The returned phase never goes beyond the last phase in _PHASE_ORDER,
        even when the last logged phase has a fingerprint.

        Feature: plan-feature-refactoring, Property 13: Reconnect state reconstruction from transition log

        **Validates: Requirements 17.1**
        """
        log = [{
            "timestamp": "t1",
            "from_node": "some_node",
            "to_node": "next",
            "subgraph": phase_name,
            "reason": "step_complete",
            "budget_snapshot": {},
        }]
        state = {"transition_log": log, "fingerprints": fingerprints}
        phase, step, progress = PlanDispatcher._reconstruct_phase_from_log(state)

        assert phase in _PHASE_ORDER, (
            f"Returned phase {phase!r} is not in _PHASE_ORDER"
        )
        # Phase index should never exceed the last phase
        assert _PHASE_ORDER.index(phase) <= len(_PHASE_ORDER) - 1
