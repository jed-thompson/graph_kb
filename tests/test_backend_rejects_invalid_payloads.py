"""Property-based test for backend rejection of invalid payloads.

Property 2: Backend Rejects Invalid Payloads — For any payload violating
            Pydantic constraints (empty name, percent outside [0.0, 1.0],
            invalid PhaseId, empty session_id), the Dispatcher rejects and
            emits spec.error with code VALIDATION_ERROR.

**Validates: Requirements 1.5, 1.6, 2.1, 2.2, 2.3, 2.5, 19.5**
"""

import pytest
from hypothesis import given, settings, HealthCheck, assume, strategies as st
from pydantic import ValidationError

from graph_kb_api.websocket.events import (
    PhaseId,
    SpecStartPayload,
    SpecPhaseInputPayload,
    SpecNavigatePayload,
    SpecPhaseProgressData,
)


# ---------------------------------------------------------------------------
# Strategies — invalid inputs
# ---------------------------------------------------------------------------

VALID_PHASE_VALUES = {p.value for p in PhaseId}

# Strings that are guaranteed NOT to be valid PhaseId values
invalid_phase_st = st.text(min_size=1, max_size=50).filter(
    lambda s: s not in VALID_PHASE_VALUES
)

# Non-empty session ids for use in otherwise-valid payloads
nonempty_session_id_st = st.text(
    min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "Pd"))
)

phase_id_st = st.sampled_from(list(PhaseId))

json_safe_dict_st = st.dictionaries(
    st.text(min_size=1, max_size=20),
    st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=30)),
    max_size=5,
)


# ---------------------------------------------------------------------------
# Property 2: Backend Rejects Invalid Payloads
# ---------------------------------------------------------------------------


class TestBackendRejectsInvalidPayloads:
    """Property 2: Backend Rejects Invalid Payloads — For any payload
    violating Pydantic constraints, a ValidationError is raised.

    **Validates: Requirements 1.5, 1.6, 2.1, 2.2, 2.3, 2.5, 19.5**
    """

    # -- SpecStartPayload: empty name ----------------------------------------

    @given(description=st.one_of(st.none(), st.text(max_size=100)))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_start_rejects_empty_name(self, description):
        """SpecStartPayload rejects name with length < 1."""
        with pytest.raises(ValidationError):
            SpecStartPayload(name="", description=description)

    # -- SpecStartPayload: name too long (> 255 chars) -----------------------

    @given(
        extra_len=st.integers(min_value=1, max_value=500),
        description=st.one_of(st.none(), st.text(max_size=100)),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_start_rejects_name_too_long(self, extra_len, description):
        """SpecStartPayload rejects name with length > 255."""
        long_name = "a" * (256 + extra_len)
        with pytest.raises(ValidationError):
            SpecStartPayload(name=long_name, description=description)

    # -- SpecPhaseInputPayload: empty session_id -----------------------------

    @given(phase=phase_id_st, data=json_safe_dict_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_phase_input_rejects_empty_session_id(self, phase, data):
        """SpecPhaseInputPayload rejects empty session_id."""
        with pytest.raises(ValidationError):
            SpecPhaseInputPayload(session_id="", phase=phase, data=data)

    # -- SpecPhaseInputPayload: invalid phase --------------------------------

    @given(
        session_id=nonempty_session_id_st,
        bad_phase=invalid_phase_st,
        data=json_safe_dict_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_phase_input_rejects_invalid_phase(self, session_id, bad_phase, data):
        """SpecPhaseInputPayload rejects a phase string not in PhaseId."""
        with pytest.raises(ValidationError):
            SpecPhaseInputPayload(session_id=session_id, phase=bad_phase, data=data)

    # -- SpecNavigatePayload: empty session_id -------------------------------

    @given(target=phase_id_st, confirm=st.booleans())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_navigate_rejects_empty_session_id(self, target, confirm):
        """SpecNavigatePayload rejects empty session_id."""
        with pytest.raises(ValidationError):
            SpecNavigatePayload(
                session_id="", target_phase=target, confirm_cascade=confirm
            )

    # -- SpecNavigatePayload: invalid target_phase ---------------------------

    @given(
        session_id=nonempty_session_id_st,
        bad_phase=invalid_phase_st,
        confirm=st.booleans(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_navigate_rejects_invalid_target_phase(
        self, session_id, bad_phase, confirm
    ):
        """SpecNavigatePayload rejects a target_phase not in PhaseId."""
        with pytest.raises(ValidationError):
            SpecNavigatePayload(
                session_id=session_id,
                target_phase=bad_phase,
                confirm_cascade=confirm,
            )

    # -- SpecPhaseProgressData: percent < 0 ----------------------------------

    @given(
        session_id=nonempty_session_id_st,
        phase=phase_id_st,
        message=st.text(max_size=100),
        bad_pct=st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_progress_rejects_percent_below_zero(
        self, session_id, phase, message, bad_pct
    ):
        """SpecPhaseProgressData rejects percent < 0.0."""
        with pytest.raises(ValidationError):
            SpecPhaseProgressData(
                session_id=session_id,
                phase=phase,
                message=message,
                percent=bad_pct,
            )

    # -- SpecPhaseProgressData: percent > 1 ----------------------------------

    @given(
        session_id=nonempty_session_id_st,
        phase=phase_id_st,
        message=st.text(max_size=100),
        bad_pct=st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_progress_rejects_percent_above_one(
        self, session_id, phase, message, bad_pct
    ):
        """SpecPhaseProgressData rejects percent > 1.0."""
        with pytest.raises(ValidationError):
            SpecPhaseProgressData(
                session_id=session_id,
                phase=phase,
                message=message,
                percent=bad_pct,
            )


class TestValidPayloadsAccepted:
    """Sanity check: valid payloads do NOT raise errors."""

    @given(
        name=st.text(min_size=1, max_size=255),
        description=st.one_of(st.none(), st.text(max_size=200)),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_spec_start_accepted(self, name, description):
        """SpecStartPayload accepts valid name (1-255 chars)."""
        payload = SpecStartPayload(name=name, description=description)
        assert payload.name == name

    @given(
        session_id=nonempty_session_id_st,
        phase=phase_id_st,
        data=json_safe_dict_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_phase_input_accepted(self, session_id, phase, data):
        """SpecPhaseInputPayload accepts valid inputs."""
        payload = SpecPhaseInputPayload(session_id=session_id, phase=phase, data=data)
        assert payload.session_id == session_id
        assert payload.phase == phase

    @given(
        session_id=nonempty_session_id_st,
        target=phase_id_st,
        confirm=st.booleans(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_navigate_accepted(self, session_id, target, confirm):
        """SpecNavigatePayload accepts valid inputs."""
        payload = SpecNavigatePayload(
            session_id=session_id, target_phase=target, confirm_cascade=confirm
        )
        assert payload.session_id == session_id
        assert payload.target_phase == target

    @given(
        session_id=nonempty_session_id_st,
        phase=phase_id_st,
        message=st.text(max_size=200),
        pct=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_progress_accepted(self, session_id, phase, message, pct):
        """SpecPhaseProgressData accepts percent in [0.0, 1.0]."""
        payload = SpecPhaseProgressData(
            session_id=session_id, phase=phase, message=message, percent=pct
        )
        assert 0.0 <= payload.percent <= 1.0
