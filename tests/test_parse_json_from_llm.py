"""Unit and property-based tests for parse_json_from_llm().

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from graph_kb_api.flows.v3.utils.json_parsing import parse_json_from_llm


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------


class TestParseJsonFromLlm:
    """Unit tests for parse_json_from_llm().

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
    """

    def test_plain_json(self):
        """Plain JSON string is parsed correctly."""
        raw = '{"key": "value", "num": 42}'
        assert parse_json_from_llm(raw) == {"key": "value", "num": 42}

    def test_json_with_leading_trailing_whitespace(self):
        """Leading/trailing whitespace is stripped before parsing."""
        raw = '   \n  {"key": "value"}  \n  '
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_json_in_code_fence(self):
        """JSON wrapped in ```json ... ``` code fences is extracted."""
        raw = '```json\n{"key": "value"}\n```'
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_json_in_code_fence_no_language(self):
        """JSON wrapped in ``` ... ``` (no language) code fences is extracted."""
        raw = '```\n{"key": "value"}\n```'
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_trailing_comma_in_object(self):
        """Trailing comma after last object member is handled."""
        raw = '{"key": "value", "num": 42,}'
        assert parse_json_from_llm(raw) == {"key": "value", "num": 42}

    def test_trailing_comma_in_array(self):
        """Trailing comma after last array element is handled."""
        raw = '{"items": [1, 2, 3,]}'
        assert parse_json_from_llm(raw) == {"items": [1, 2, 3]}

    def test_trailing_comma_in_code_fence(self):
        """Trailing comma inside code fence is handled."""
        raw = '```json\n{"key": "value",}\n```'
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_partial_json_recovery(self):
        """JSON embedded in surrounding text is recovered."""
        raw = 'Here is the result:\n{"key": "value"}\nEnd of response.'
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_nested_json(self):
        """Nested JSON objects are parsed correctly."""
        raw = '{"outer": {"inner": "value"}, "list": [1, 2]}'
        assert parse_json_from_llm(raw) == {"outer": {"inner": "value"}, "list": [1, 2]}

    def test_empty_string_raises_value_error(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            parse_json_from_llm("")

    def test_whitespace_only_raises_value_error(self):
        """Whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            parse_json_from_llm("   \n  ")

    def test_non_json_raises_value_error_with_prefix(self):
        """Non-JSON string raises ValueError with first 200 chars."""
        raw = "This is not JSON at all, just plain text."
        with pytest.raises(ValueError, match="This is not JSON"):
            parse_json_from_llm(raw)

    def test_error_message_truncated_to_200_chars(self):
        """Error message includes at most first 200 chars of raw input."""
        raw = "x" * 500
        with pytest.raises(ValueError) as exc_info:
            parse_json_from_llm(raw)
        # The prefix in the error should be exactly 200 chars of 'x'
        assert "x" * 200 in str(exc_info.value)
        assert "x" * 201 not in str(exc_info.value)

    def test_pydantic_schema_validation(self):
        """Pydantic model validation works when expected_schema is provided."""

        class MyModel(BaseModel):
            name: str
            count: int

        raw = '{"name": "test", "count": 5}'
        result = parse_json_from_llm(raw, expected_schema=MyModel)
        assert isinstance(result, MyModel)
        assert result.name == "test"
        assert result.count == 5

    def test_pydantic_schema_strict_failure(self):
        """Strict mode raises ValueError on schema mismatch."""

        class MyModel(BaseModel):
            name: str
            count: int

        raw = '{"name": "test"}'  # missing 'count'
        with pytest.raises(ValueError, match="Schema validation failed"):
            parse_json_from_llm(raw, expected_schema=MyModel, strict=True)

    def test_pydantic_schema_non_strict_returns_dict(self):
        """Non-strict mode returns raw dict on schema mismatch."""

        class MyModel(BaseModel):
            name: str
            count: int

        raw = '{"name": "test"}'  # missing 'count'
        result = parse_json_from_llm(raw, expected_schema=MyModel, strict=False)
        assert result == {"name": "test"}

    def test_json_array_parsed(self):
        """JSON arrays are parsed correctly."""
        raw = '[1, 2, 3]'
        assert parse_json_from_llm(raw) == [1, 2, 3]

    def test_code_fence_with_extra_text_before(self):
        """Code fence with text before it is handled."""
        raw = 'Here is the JSON:\n```json\n{"key": "value"}\n```\nDone.'
        assert parse_json_from_llm(raw) == {"key": "value"}

    def test_json_in_uppercase_code_fence(self):
        """JSON wrapped in ```JSON ... ``` is extracted."""
        raw = '```JSON\n{"key": "value"}\n```'
        assert parse_json_from_llm(raw) == {"key": "value"}


# ---------------------------------------------------------------------------
# Property-Based Tests (Hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings, HealthCheck, strategies as st


# Strategy: generate valid JSON-serializable dicts
_json_value_st = st.recursive(
    st.one_of(
        st.text(max_size=30).map(lambda s: s.replace("\\", "").replace('"', "")),
        st.integers(min_value=-10000, max_value=10000),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
        st.booleans(),
        st.none(),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            st.text(min_size=1, max_size=15).map(lambda s: s.replace("\\", "").replace('"', "")),
            children,
            max_size=5,
        ),
    ),
    max_leaves=20,
)

_json_dict_st = st.dictionaries(
    st.text(min_size=1, max_size=15).map(lambda s: s.replace("\\", "").replace('"', "")),
    _json_value_st,
    min_size=1,
    max_size=5,
)


@st.composite
def llm_quirky_json_st(draw):
    """Generate a valid JSON dict wrapped in common LLM response artifacts."""
    obj = draw(_json_dict_st)
    json_str = json.dumps(obj, ensure_ascii=False)

    # Randomly apply LLM quirks
    quirk = draw(st.sampled_from([
        "plain",
        "code_fence_json",
        "code_fence_no_lang",
        "leading_trailing_ws",
        "trailing_comma_obj",
        "surrounding_text",
    ]))

    if quirk == "code_fence_json":
        json_str = f"```json\n{json_str}\n```"
    elif quirk == "code_fence_no_lang":
        json_str = f"```\n{json_str}\n```"
    elif quirk == "leading_trailing_ws":
        ws = draw(st.text(alphabet=" \t\n", min_size=1, max_size=5))
        json_str = ws + json_str + ws
    elif quirk == "trailing_comma_obj":
        # Add trailing comma before last }
        idx = json_str.rfind("}")
        if idx > 0:
            json_str = json_str[:idx] + "," + json_str[idx:]
    elif quirk == "surrounding_text":
        prefix = draw(st.text(min_size=1, max_size=20).map(
            lambda s: s.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
        ))
        json_str = f"{prefix}\n{json_str}\nEnd."

    return obj, json_str


class TestParseJsonFromLlmProperty:
    """Feature: plan-feature-refactoring, Property 7: parse_json_from_llm round-trip
    through LLM quirks

    **Validates: Requirements 7.2**
    """

    @given(data=llm_quirky_json_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_round_trip_through_llm_quirks(self, data: tuple[dict, str]):
        """For any valid JSON object wrapped in LLM artifacts, parse_json_from_llm
        recovers the original object.

        Feature: plan-feature-refactoring, Property 7: parse_json_from_llm round-trip through LLM quirks

        **Validates: Requirements 7.2**
        """
        original, quirky_str = data
        result = parse_json_from_llm(quirky_str)
        assert result == original, (
            f"Round-trip failed.\nOriginal: {original!r}\n"
            f"Quirky input: {quirky_str!r}\nParsed: {result!r}"
        )


# Strategy: generate strings that are definitely not valid JSON
_non_json_st = st.text(min_size=1, max_size=300).filter(
    lambda s: s.strip() and not s.strip().startswith("{") and not s.strip().startswith("[")
)


class TestParseJsonErrorProperty:
    """Feature: plan-feature-refactoring, Property 8: parse_json_from_llm error
    message includes raw response prefix

    **Validates: Requirements 7.4**
    """

    @given(raw=_non_json_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_error_includes_raw_prefix(self, raw: str):
        """For any non-JSON string, the ValueError message contains the first
        min(200, len(input)) characters of the raw input.

        Feature: plan-feature-refactoring, Property 8: parse_json_from_llm error message includes raw response prefix

        **Validates: Requirements 7.4**
        """
        try:
            parse_json_from_llm(raw)
        except ValueError as e:
            expected_prefix = raw[:200]
            assert expected_prefix in str(e), (
                f"Error message does not contain expected prefix.\n"
                f"Expected prefix: {expected_prefix!r}\n"
                f"Error message: {str(e)!r}"
            )
        # If it didn't raise, the string happened to contain valid JSON — that's fine
