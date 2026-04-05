"""Property-based test for plan output validity.

Property 19: Plan Output Validity — For any result from ``run_plan``,
             ``phases`` is non-empty and ``total_estimated_days`` is a
             positive integer.

**Validates: Requirements 12.3**

Since ``run_plan`` is currently a stub (raises NotImplementedError),
these tests validate the *contract* that any dict returned by
``run_plan`` must satisfy.  A helper ``check_plan_output_contract``
encodes the invariant and is exercised with Hypothesis-generated data.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st


# ---------------------------------------------------------------------------
# Contract helper
# ---------------------------------------------------------------------------


def check_plan_output_contract(result: Dict[str, Any]) -> None:
    """Assert that a run_plan result satisfies the plan output contract.

    Raises ``AssertionError`` if:
    - ``phases`` key is missing
    - ``phases`` is not a list
    - ``phases`` is empty
    - ``total_estimated_days`` key is missing
    - ``total_estimated_days`` is not an int
    - ``total_estimated_days`` is not positive (> 0)
    """
    # phases checks
    assert "phases" in result, "run_plan result must contain 'phases'"
    phases = result["phases"]
    assert isinstance(phases, list), (
        f"phases must be a list, got {type(phases).__name__}"
    )
    assert len(phases) > 0, "phases must be non-empty"

    # total_estimated_days checks
    assert "total_estimated_days" in result, (
        "run_plan result must contain 'total_estimated_days'"
    )
    days = result["total_estimated_days"]
    assert isinstance(days, int) and not isinstance(days, bool), (
        f"total_estimated_days must be an int, got {type(days).__name__}"
    )
    assert days > 0, f"total_estimated_days must be positive, got {days}"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid phases: non-empty lists of dicts (each dict represents a plan phase)
valid_phases_st = st.lists(
    st.dictionaries(st.text(min_size=1, max_size=20), st.text(max_size=50)),
    min_size=1,
    max_size=10,
)

# Valid total_estimated_days: positive integers
valid_days_st = st.integers(min_value=1, max_value=10_000)


def _plan_result(
    phases: List[Any],
    total_estimated_days: Any,
) -> Dict[str, Any]:
    """Build a minimal run_plan result dict."""
    return {
        "phases": phases,
        "milestones": [],
        "risk_mitigations": [],
        "total_estimated_days": total_estimated_days,
        "critical_path": [],
    }


# ---------------------------------------------------------------------------
# Property 19: Plan Output Validity
# ---------------------------------------------------------------------------


class TestPlanOutputValidity:
    """Property 19: Plan Output Validity — For any result from ``run_plan``,
    ``phases`` is non-empty and ``total_estimated_days`` is a positive integer.

    **Validates: Requirements 12.3**
    """

    @given(phases=valid_phases_st, days=valid_days_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_plan_results_pass_contract(self, phases: List[Any], days: int):
        """Any plan with non-empty phases and positive int days satisfies the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result(phases, days)
        # Should not raise
        check_plan_output_contract(result)

    def test_missing_phases_fails_contract(self):
        """A result dict without phases fails the contract.

        **Validates: Requirements 12.3**
        """
        result = {
            "milestones": [],
            "risk_mitigations": [],
            "total_estimated_days": 5,
            "critical_path": [],
        }
        with pytest.raises(AssertionError, match="must contain 'phases'"):
            check_plan_output_contract(result)

    def test_empty_phases_fails_contract(self):
        """A result with an empty phases list fails the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result([], 5)
        with pytest.raises(AssertionError, match="must be non-empty"):
            check_plan_output_contract(result)

    @given(
        phases=st.one_of(
            st.text(min_size=0, max_size=10),
            st.integers(),
            st.none(),
            st.dictionaries(st.text(max_size=5), st.integers()),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_list_phases_fails_contract(self, phases: Any):
        """A non-list phases value fails the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result(phases, 5)
        with pytest.raises(AssertionError, match="must be a list"):
            check_plan_output_contract(result)

    def test_missing_total_estimated_days_fails_contract(self):
        """A result dict without total_estimated_days fails the contract.

        **Validates: Requirements 12.3**
        """
        result = {
            "phases": [{"name": "Phase 1"}],
            "milestones": [],
            "risk_mitigations": [],
            "critical_path": [],
        }
        with pytest.raises(AssertionError, match="must contain 'total_estimated_days'"):
            check_plan_output_contract(result)

    @given(days=st.integers(max_value=0))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_non_positive_days_fails_contract(self, days: int):
        """Zero or negative total_estimated_days fails the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result([{"name": "Phase 1"}], days)
        with pytest.raises(AssertionError, match="must be positive"):
            check_plan_output_contract(result)

    @given(
        days=st.one_of(
            st.floats(allow_nan=True, allow_infinity=True),
            st.text(min_size=1, max_size=10),
            st.none(),
            st.lists(st.integers(), max_size=2),
            st.booleans(),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_int_days_fails_contract(self, days: Any):
        """A non-integer total_estimated_days fails the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result([{"name": "Phase 1"}], days)
        with pytest.raises(AssertionError, match="must be an int"):
            check_plan_output_contract(result)

    def test_boundary_value_one_day_passes(self):
        """Boundary value: 1 day (minimum positive int) passes the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result([{"name": "Phase 1"}], 1)
        check_plan_output_contract(result)

    def test_single_phase_passes(self):
        """Boundary value: single-element phases list passes the contract.

        **Validates: Requirements 12.3**
        """
        result = _plan_result([{"name": "Phase 1"}], 10)
        check_plan_output_contract(result)
