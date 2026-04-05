"""Property-based tests for progress calculation and emit_phase_progress.

Property 16: Progress Calculation Bounds and Weighted Sum — calculate_overall_progress
always returns a value in [0.0, 1.0], equals 1.0 when all phases are completed,
equals 0.0 when no phases are completed with zero current progress, and computes
a correct weighted sum using PHASE_WEIGHTS.

**Validates: Requirements 22.1, 22.2, 22.3, 22.4**

Property 18: emit_phase_progress Optional Field Omission — When optional parameters
are not provided, they are omitted from the emitted event payload. When optional
parameters are provided, they are included in the payload.

**Validates: Requirement 23.3**
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.state.plan_state import PHASE_WEIGHTS
from graph_kb_api.websocket.plan_events import (
    calculate_overall_progress,
    emit_phase_progress,
    set_plan_ws_manager,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

phase_keys_st = st.sampled_from(list(PHASE_WEIGHTS.keys()))


@st.composite
def completed_phases_dict(draw: st.DrawFn):
    """Generate a dict mapping PHASE_WEIGHTS keys to booleans."""
    return {phase: draw(st.booleans()) for phase in PHASE_WEIGHTS}


@st.composite
def progress_inputs(draw: st.DrawFn):
    """Generate full inputs for calculate_overall_progress."""
    completed = draw(completed_phases_dict())
    current_phase = draw(phase_keys_st)
    current_progress = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    return completed, current_phase, current_progress


# ---------------------------------------------------------------------------
# Property 16: Progress Calculation Bounds and Weighted Sum
# ---------------------------------------------------------------------------


class TestProgressCalculationBoundsAndWeightedSum:
    """Property 16: Progress Calculation Bounds and Weighted Sum

    calculate_overall_progress always returns a value in [0.0, 1.0],
    equals 1.0 when all phases are completed, equals 0.0 when no phases
    are completed with zero current progress, and computes a correct
    weighted sum using PHASE_WEIGHTS.

    **Validates: Requirements 22.1, 22.2, 22.3, 22.4**
    """

    @given(data=progress_inputs())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_result_always_in_bounds(self, data):
        """calculate_overall_progress always returns a value in [0.0, 1.0]."""
        completed, current_phase, current_progress = data
        result = calculate_overall_progress(completed, current_phase, current_progress)
        assert 0.0 <= result <= 1.0, f"Expected result in [0.0, 1.0], got {result}"

    @given(current_phase=phase_keys_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_all_completed_returns_one(self, current_phase):
        """When all phases are completed, the result should be 1.0."""
        completed = {phase: True for phase in PHASE_WEIGHTS}
        result = calculate_overall_progress(completed, current_phase, 0.0)
        assert abs(result - 1.0) < 1e-9, (
            f"Expected 1.0 when all phases completed, got {result}"
        )

    @given(current_phase=phase_keys_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_none_completed_zero_progress_returns_zero(self, current_phase):
        """When no phases are completed and current_phase_progress is 0.0, result is 0.0."""
        completed = {phase: False for phase in PHASE_WEIGHTS}
        result = calculate_overall_progress(completed, current_phase, 0.0)
        assert abs(result) < 1e-9, (
            f"Expected 0.0 when no phases completed and progress is 0.0, got {result}"
        )

    @given(data=progress_inputs())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_weighted_sum_correctness(self, data):
        """The result should be a weighted sum using PHASE_WEIGHTS."""
        completed, current_phase, current_progress = data

        expected = 0.0
        for phase, weight in PHASE_WEIGHTS.items():
            if completed.get(phase):
                expected += weight
            elif phase == current_phase:
                expected += weight * current_progress
        expected = min(expected, 1.0)

        result = calculate_overall_progress(completed, current_phase, current_progress)
        assert abs(result - expected) < 1e-9, (
            f"Expected weighted sum {expected}, got {result}"
        )


# ---------------------------------------------------------------------------
# Property 18: emit_phase_progress Optional Field Omission
# ---------------------------------------------------------------------------

# Optional parameter names and their sample values for testing
OPTIONAL_PARAMS = {
    "substep": st.text(min_size=1, max_size=30),
    "task_id": st.text(min_size=1, max_size=20),
    "task_progress": st.text(min_size=1, max_size=20),
    "iteration": st.integers(min_value=1, max_value=100),
    "max_iterations": st.integers(min_value=1, max_value=100),
    "agent_type": st.text(min_size=1, max_size=20),
    "confidence": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
}


@st.composite
def optional_params_subset(draw: st.DrawFn):
    """Generate a random subset of optional params with values, and the rest as None."""
    included = {}
    excluded_keys = []
    for key, strategy in OPTIONAL_PARAMS.items():
        if draw(st.booleans()):
            included[key] = draw(strategy)
        else:
            excluded_keys.append(key)
    return included, excluded_keys


class TestEmitPhaseProgressOptionalFieldOmission:
    """Property 18: emit_phase_progress Optional Field Omission

    When optional parameters are not provided, they should be omitted
    from the emitted event payload. When optional parameters are provided,
    they should be included in the payload.

    **Validates: Requirement 23.3**
    """

    @given(
        session_id=st.text(min_size=1, max_size=30),
        phase=phase_keys_st,
        step=st.text(min_size=1, max_size=20),
        message=st.text(min_size=1, max_size=40),
        progress_pct=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        optional_data=optional_params_subset(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_optional_fields_omitted_or_included(
        self, session_id, phase, step, message, progress_pct, optional_data
    ):
        """Optional params are omitted from payload when not provided,
        and included when provided."""
        included, excluded_keys = optional_data

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock()

        set_plan_ws_manager(mock_manager)
        try:
            await emit_phase_progress(
                session_id=session_id,
                phase=phase,
                step=step,
                message=message,
                progress_pct=progress_pct,
                client_id="test-client",
                **included,
            )

            mock_manager.send_event.assert_called_once()
            call_kwargs = mock_manager.send_event.call_args
            payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")

            # Included optional fields should be present in the payload
            for key, value in included.items():
                assert key in payload, (
                    f"Optional field '{key}' was provided but missing from payload"
                )
                assert payload[key] == value, (
                    f"Optional field '{key}' has wrong value: "
                    f"expected {value!r}, got {payload[key]!r}"
                )

            # Excluded optional fields should NOT be present in the payload
            for key in excluded_keys:
                assert key not in payload, (
                    f"Optional field '{key}' was not provided but found in payload"
                )
        finally:
            set_plan_ws_manager(None)

    @given(
        session_id=st.text(min_size=1, max_size=30),
        phase=phase_keys_st,
        step=st.text(min_size=1, max_size=20),
        message=st.text(min_size=1, max_size=40),
        progress_pct=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_no_optional_fields_means_minimal_payload(
        self, session_id, phase, step, message, progress_pct
    ):
        """When no optional params are provided, payload contains only required fields."""
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock()

        set_plan_ws_manager(mock_manager)
        try:
            await emit_phase_progress(
                session_id=session_id,
                phase=phase,
                step=step,
                message=message,
                progress_pct=progress_pct,
                client_id="test-client",
            )

            mock_manager.send_event.assert_called_once()
            call_kwargs = mock_manager.send_event.call_args
            payload = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")

            for key in OPTIONAL_PARAMS:
                assert key not in payload, (
                    f"Optional field '{key}' should not be in payload when not provided"
                )
        finally:
            set_plan_ws_manager(None)
