"""Property-based tests for SubgraphProgressData percent validation.

Property 14: SubgraphProgressData Percent Validation — For any float value
outside the range [0.0, 1.0], constructing a SubgraphProgressData with that
value as ``percent`` should raise a validation error. For any float within
[0.0, 1.0], construction should succeed.

**Validates: Requirement 13.2**
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from graph_kb_api.websocket.events import PhaseId
from graph_kb_api.websocket.plan_events import SubgraphProgressData

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

phase_id_st = st.sampled_from(list(PhaseId))


@st.composite
def valid_progress_kwargs(draw: st.DrawFn, percent: float | None = None):
    """Build keyword arguments for SubgraphProgressData with a given percent.

    If *percent* is ``None`` the caller is expected to supply it separately.
    """
    kwargs = {
        "session_id": draw(st.text(min_size=1, max_size=30)),
        "phase": draw(phase_id_st),
        "step": draw(st.text(min_size=1, max_size=30)),
        "message": draw(st.text(min_size=1, max_size=60)),
    }
    if percent is not None:
        kwargs["percent"] = percent
    return kwargs


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestSubgraphProgressDataPercentValidation:
    """Property 14: SubgraphProgressData Percent Validation

    The ``percent`` field must be constrained to [0.0, 1.0] inclusive.
    Values outside this range must be rejected with a ``ValidationError``.

    **Validates: Requirement 13.2**
    """

    @given(
        kwargs=valid_progress_kwargs(),
        percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_percent_accepted(self, kwargs, percent):
        """Percent values in [0.0, 1.0] are accepted without error."""
        data = SubgraphProgressData(**kwargs, percent=percent)
        assert 0.0 <= data.percent <= 1.0

    @given(
        kwargs=valid_progress_kwargs(),
        percent=st.floats(max_value=-0.0001, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_percent_below_zero_rejected(self, kwargs, percent):
        """Percent values below 0.0 raise ValidationError."""
        with pytest.raises(ValidationError):
            SubgraphProgressData(**kwargs, percent=percent)

    @given(
        kwargs=valid_progress_kwargs(),
        percent=st.floats(min_value=1.0001, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_percent_above_one_rejected(self, kwargs, percent):
        """Percent values above 1.0 raise ValidationError."""
        with pytest.raises(ValidationError):
            SubgraphProgressData(**kwargs, percent=percent)

    @given(kwargs=valid_progress_kwargs())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_boundary_zero_accepted(self, kwargs):
        """Boundary value 0.0 is accepted."""
        data = SubgraphProgressData(**kwargs, percent=0.0)
        assert data.percent == 0.0

    @given(kwargs=valid_progress_kwargs())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_boundary_one_accepted(self, kwargs):
        """Boundary value 1.0 is accepted."""
        data = SubgraphProgressData(**kwargs, percent=1.0)
        assert data.percent == 1.0
