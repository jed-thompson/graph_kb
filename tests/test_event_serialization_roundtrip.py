"""Property-based test for event serialization round-trip.

Property 1: Event Serialization Round-Trip — For any valid server-to-client
            event, serializing via Pydantic to JSON and deserializing back
            produces an equivalent object.

**Validates: Requirements 2.4**
"""

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.websocket.events import (
    PhaseId,
    PhaseField,
    SpecPhasePromptData,
    SpecPhaseProgressData,
    SpecPhaseCompleteData,
    SpecErrorData,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

phase_id_st = st.sampled_from(list(PhaseId))

field_type_st = st.sampled_from(
    ["text", "textarea", "select", "file", "multiselect", "json"]
)

phase_field_st = st.builds(
    PhaseField,
    id=st.text(
        min_size=1, max_size=50, alphabet=st.characters(categories=("L", "N", "Pd"))
    ),
    label=st.text(min_size=1, max_size=100),
    type=field_type_st,
    required=st.booleans(),
    options=st.one_of(
        st.none(), st.lists(st.text(min_size=1, max_size=30), max_size=5)
    ),
    placeholder=st.one_of(st.none(), st.text(max_size=100)),
)

# JSON-safe values for Dict[str, Any] fields (avoid non-serializable types)
json_safe_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(2**53), max_value=2**53),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
    ),
    max_leaves=10,
)

json_safe_dict_st = st.dictionaries(
    st.text(min_size=1, max_size=20),
    json_safe_values,
    max_size=5,
)

# Model strategies

prompt_data_st = st.builds(
    SpecPhasePromptData,
    session_id=st.text(min_size=1, max_size=50),
    phase=phase_id_st,
    fields=st.lists(phase_field_st, max_size=5),
    prefilled=st.one_of(st.none(), json_safe_dict_st),
)

progress_data_st = st.builds(
    SpecPhaseProgressData,
    session_id=st.text(min_size=1, max_size=50),
    phase=phase_id_st,
    message=st.text(max_size=200),
    percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    agent_content=st.one_of(st.none(), st.text(max_size=200)),
)

complete_data_st = st.builds(
    SpecPhaseCompleteData,
    session_id=st.text(min_size=1, max_size=50),
    phase=phase_id_st,
    result=json_safe_dict_st,
)

error_data_st = st.builds(
    SpecErrorData,
    message=st.text(min_size=1, max_size=200),
    code=st.text(min_size=1, max_size=50),
    phase=st.one_of(st.none(), phase_id_st),
)


# ---------------------------------------------------------------------------
# Property 1: Event Serialization Round-Trip
# ---------------------------------------------------------------------------


class TestEventSerializationRoundTrip:
    """Property 1: Event Serialization Round-Trip — For any valid
    server-to-client event, serializing via Pydantic to JSON and
    deserializing back produces an equivalent object.

    **Validates: Requirements 2.4**
    """

    @given(data=prompt_data_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_prompt_data_roundtrip(self, data: SpecPhasePromptData):
        """SpecPhasePromptData survives JSON serialization round-trip."""
        json_str = data.model_dump_json()
        restored = SpecPhasePromptData.model_validate_json(json_str)
        assert restored == data

    @given(data=progress_data_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_progress_data_roundtrip(self, data: SpecPhaseProgressData):
        """SpecPhaseProgressData survives JSON serialization round-trip."""
        json_str = data.model_dump_json()
        restored = SpecPhaseProgressData.model_validate_json(json_str)
        assert restored == data

    @given(data=complete_data_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_complete_data_roundtrip(self, data: SpecPhaseCompleteData):
        """SpecPhaseCompleteData survives JSON serialization round-trip."""
        json_str = data.model_dump_json()
        restored = SpecPhaseCompleteData.model_validate_json(json_str)
        assert restored == data

    @given(data=error_data_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_error_data_roundtrip(self, data: SpecErrorData):
        """SpecErrorData survives JSON serialization round-trip."""
        json_str = data.model_dump_json()
        restored = SpecErrorData.model_validate_json(json_str)
        assert restored == data
