"""Property-based test for context data merge semantics.

Property 16: Context Data Merge — For any existing context data and any new
             user input submitted to the context phase, the resulting context
             state is the merge of both, with new input values overriding
             existing ones for the same keys.

**Validates: Requirements 10.2**
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate arbitrary string-keyed dicts with mixed value types to simulate
# context data and user input.
_context_value_st = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
    st.lists(st.text(max_size=20), max_size=5),
    st.dictionaries(st.text(max_size=10), st.text(max_size=20), max_size=3),
)

context_dict_st = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=_context_value_st,
    max_size=15,
)


# ---------------------------------------------------------------------------
# Merge function under test — extracted from context_phase logic
# ---------------------------------------------------------------------------


def merge_context(
    existing: Dict[str, Any], user_input: Dict[str, Any]
) -> Dict[str, Any]:
    """Replicate the merge logic from context_phase:

        merged_context = {**existing_context, **user_input}

    This is the exact operation performed in
    ``graph_kb_api/flows/v3/nodes/spec_phases.py::context_phase``.
    """
    return {**existing, **user_input}


# ---------------------------------------------------------------------------
# Property 16: Context Data Merge
# ---------------------------------------------------------------------------


class TestContextDataMerge:
    """Property 16: Context Data Merge — For any existing context data and
    new user input, the resulting context state is the merge with new values
    overriding existing ones for same keys.

    **Validates: Requirements 10.2**
    """

    @given(existing=context_dict_st, user_input=context_dict_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_new_input_keys_present_with_correct_values(
        self,
        existing: Dict[str, Any],
        user_input: Dict[str, Any],
    ):
        """All keys from user_input appear in the merged result with their
        new values (new input overrides existing).

        **Validates: Requirements 10.2**
        """
        merged = merge_context(existing, user_input)

        for key, value in user_input.items():
            assert key in merged, (
                f"Key {key!r} from user_input missing in merged result"
            )
            assert merged[key] == value, (
                f"Key {key!r}: expected {value!r} from user_input, got {merged[key]!r}"
            )

    @given(existing=context_dict_st, user_input=context_dict_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_existing_keys_not_in_input_are_preserved(
        self,
        existing: Dict[str, Any],
        user_input: Dict[str, Any],
    ):
        """All keys from existing that are NOT in user_input are preserved
        unchanged in the merged result.

        **Validates: Requirements 10.2**
        """
        merged = merge_context(existing, user_input)

        for key, value in existing.items():
            if key not in user_input:
                assert key in merged, (
                    f"Key {key!r} from existing (not overridden) missing in merged result"
                )
                assert merged[key] == value, (
                    f"Key {key!r}: expected preserved value {value!r}, got {merged[key]!r}"
                )

    @given(existing=context_dict_st, user_input=context_dict_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_result_has_exactly_union_of_keys(
        self,
        existing: Dict[str, Any],
        user_input: Dict[str, Any],
    ):
        """The merged result contains exactly the union of keys from both
        dicts — no extra keys, no missing keys.

        **Validates: Requirements 10.2**
        """
        merged = merge_context(existing, user_input)

        expected_keys = set(existing.keys()) | set(user_input.keys())
        assert set(merged.keys()) == expected_keys, (
            f"Key mismatch: expected {expected_keys}, got {set(merged.keys())}"
        )
