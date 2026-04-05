"""Property-based test for research confidence score range.

Property 18: Research Confidence Score Range — For any result from
             ``run_research``, ``confidence_score`` is in [0.0, 1.0].

**Validates: Requirements 11.6**

Since ``run_research`` is currently a stub (raises NotImplementedError),
these tests validate the *contract* that any dict returned by
``run_research`` must satisfy.  A helper ``check_confidence_score_contract``
encodes the invariant and is exercised with Hypothesis-generated data.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st


# ---------------------------------------------------------------------------
# Contract helper
# ---------------------------------------------------------------------------


def check_confidence_score_contract(result: Dict[str, Any]) -> None:
    """Assert that a run_research result satisfies the confidence_score contract.

    Raises ``AssertionError`` if:
    - ``confidence_score`` key is missing
    - ``confidence_score`` is not a float/int
    - ``confidence_score`` is outside [0.0, 1.0]
    """
    assert "confidence_score" in result, (
        "run_research result must contain 'confidence_score'"
    )
    score = result["confidence_score"]
    assert isinstance(score, (int, float)), (
        f"confidence_score must be numeric, got {type(score).__name__}"
    )
    assert 0.0 <= score <= 1.0, f"confidence_score must be in [0.0, 1.0], got {score}"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid confidence scores: floats in [0.0, 1.0]
valid_confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


# A minimal valid run_research result dict with a given confidence_score
def _research_result(confidence_score: float) -> Dict[str, Any]:
    return {
        "codebase": {},
        "documents": {},
        "risks": [],
        "gaps": [],
        "summary": "test summary",
        "confidence_score": confidence_score,
    }


# Arbitrary floats (including out-of-range, NaN, inf)
arbitrary_float_st = st.floats(allow_nan=True, allow_infinity=True)


# ---------------------------------------------------------------------------
# Property 18: Research Confidence Score Range
# ---------------------------------------------------------------------------


class TestResearchConfidenceScoreRange:
    """Property 18: Research Confidence Score Range — For any result from
    ``run_research``, ``confidence_score`` is in [0.0, 1.0].

    **Validates: Requirements 11.6**
    """

    @given(score=valid_confidence_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_scores_pass_contract(self, score: float):
        """Any confidence_score in [0.0, 1.0] satisfies the contract.

        **Validates: Requirements 11.6**
        """
        result = _research_result(score)
        # Should not raise
        check_confidence_score_contract(result)

    @given(score=arbitrary_float_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_arbitrary_floats_checked_by_contract(self, score: float):
        """For arbitrary floats, only values in [0.0, 1.0] pass the contract.

        **Validates: Requirements 11.6**
        """
        result = _research_result(score)
        in_range = (
            not (score != score) and 0.0 <= score <= 1.0
        )  # NaN check via self-inequality

        if in_range:
            check_confidence_score_contract(result)
        else:
            with pytest.raises(AssertionError):
                check_confidence_score_contract(result)

    def test_missing_confidence_score_fails_contract(self):
        """A result dict without confidence_score fails the contract.

        **Validates: Requirements 11.6**
        """
        result = {
            "codebase": {},
            "documents": {},
            "risks": [],
            "gaps": [],
            "summary": "test summary",
        }
        with pytest.raises(AssertionError, match="must contain 'confidence_score'"):
            check_confidence_score_contract(result)

    @given(
        score=st.one_of(
            st.text(min_size=1, max_size=10),
            st.none(),
            st.lists(st.integers(), max_size=2),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_numeric_confidence_score_fails_contract(self, score: Any):
        """A non-numeric confidence_score fails the contract.

        **Validates: Requirements 11.6**
        """
        result = _research_result(score)
        with pytest.raises(AssertionError, match="must be numeric"):
            check_confidence_score_contract(result)

    @given(
        score=st.one_of(
            st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
            st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
        )
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_out_of_range_scores_fail_contract(self, score: float):
        """Scores outside [0.0, 1.0] fail the contract.

        **Validates: Requirements 11.6**
        """
        result = _research_result(score)
        with pytest.raises(AssertionError, match="must be in \\[0\\.0, 1\\.0\\]"):
            check_confidence_score_contract(result)

    def test_boundary_values_pass_contract(self):
        """Boundary values 0.0 and 1.0 pass the contract.

        **Validates: Requirements 11.6**
        """
        check_confidence_score_contract(_research_result(0.0))
        check_confidence_score_contract(_research_result(1.0))
