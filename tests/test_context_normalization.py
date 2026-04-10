"""Unit tests for normalize_context_names().

Tests the context field name normalization utility that converts
legacy/alias field names to their canonical (ID-based) forms.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from graph_kb_api.flows.v3.utils.context_utils import (
    _FIELD_ALIASES,
    normalize_context_names,
)


class TestNormalizeContextNames:
    """Unit tests for normalize_context_names()."""

    def test_none_input_returns_empty_dict(self):
        """None context returns empty dict.

        **Validates: Requirements 2.3**
        """
        assert normalize_context_names(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        """Empty context returns empty dict.

        **Validates: Requirements 2.3**
        """
        assert normalize_context_names({}) == {}

    def test_alias_only_promoted_to_canonical(self):
        """When only alias key is present, it is promoted to canonical name.

        **Validates: Requirements 2.1**
        """
        ctx = {"primary_document": "doc-123", "spec_name": "my-spec"}
        result = normalize_context_names(ctx)

        assert "primary_document" not in result
        assert result["primary_document_id"] == "doc-123"
        assert result["spec_name"] == "my-spec"

    def test_canonical_only_unchanged(self):
        """When only canonical key is present, it passes through unchanged.

        **Validates: Requirements 2.1**
        """
        ctx = {"primary_document_id": "doc-456", "spec_name": "my-spec"}
        result = normalize_context_names(ctx)

        assert result["primary_document_id"] == "doc-456"
        assert result["spec_name"] == "my-spec"

    def test_both_present_prefers_canonical(self):
        """When both alias and canonical exist, canonical value is kept.

        **Validates: Requirements 2.4**
        """
        ctx = {
            "primary_document": "alias-value",
            "primary_document_id": "canonical-value",
        }
        result = normalize_context_names(ctx)

        assert result["primary_document_id"] == "canonical-value"
        assert "primary_document" not in result

    def test_both_present_logs_deprecation_warning(self, caplog):
        """When both alias and canonical exist, a deprecation warning is logged.

        **Validates: Requirements 2.4**
        """
        ctx = {
            "primary_document": "alias-value",
            "primary_document_id": "canonical-value",
        }
        with caplog.at_level(logging.WARNING):
            normalize_context_names(ctx)

        assert any("deprecated" in record.message.lower() for record in caplog.records)

    def test_supporting_docs_alias_promoted(self):
        """supporting_docs alias is promoted to supporting_document_ids.

        **Validates: Requirements 2.1**
        """
        ctx = {"supporting_docs": ["doc-1", "doc-2"]}
        result = normalize_context_names(ctx)

        assert "supporting_docs" not in result
        assert result["supporting_document_ids"] == ["doc-1", "doc-2"]

    def test_multiple_aliases_all_normalized(self):
        """All aliases in _FIELD_ALIASES are normalized in a single call.

        **Validates: Requirements 2.1, 2.5**
        """
        ctx = {
            "primary_document": "doc-123",
            "supporting_docs": ["doc-a"],
            "other_field": "keep-me",
        }
        result = normalize_context_names(ctx)

        assert "primary_document" not in result
        assert "supporting_docs" not in result
        assert result["primary_document_id"] == "doc-123"
        assert result["supporting_document_ids"] == ["doc-a"]
        assert result["other_field"] == "keep-me"

    def test_no_aliases_present_passthrough(self):
        """Context with no alias keys passes through unchanged.

        **Validates: Requirements 2.1**
        """
        ctx = {"spec_name": "test", "user_explanation": "hello"}
        result = normalize_context_names(ctx)

        assert result == ctx

    def test_does_not_mutate_input(self):
        """The original context dict is not mutated.

        **Validates: Requirements 2.3**
        """
        ctx = {"primary_document": "doc-123", "spec_name": "test"}
        original = dict(ctx)
        normalize_context_names(ctx)

        assert ctx == original

    def test_field_aliases_mapping_is_complete(self):
        """_FIELD_ALIASES contains the expected alias→canonical mappings."""
        assert "primary_document" in _FIELD_ALIASES
        assert _FIELD_ALIASES["primary_document"] == "primary_document_id"
        assert "supporting_docs" in _FIELD_ALIASES
        assert _FIELD_ALIASES["supporting_docs"] == "supporting_document_ids"


# ---------------------------------------------------------------------------
# Property-Based Tests (Hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings, HealthCheck, strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary values that might appear in a context dict
_context_value_st = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
    st.lists(st.text(max_size=20), max_size=5),
)

# Keys that are NOT aliases (unrelated context keys)
_non_alias_key_st = st.text(min_size=1, max_size=30).filter(
    lambda k: k not in _FIELD_ALIASES and k not in _FIELD_ALIASES.values()
)

# Strategy: random context dict with a mix of alias keys, canonical keys,
# both, and unrelated keys.
@st.composite
def context_dict_st(draw):
    """Generate a random context dict that may contain alias keys, canonical
    keys, both for the same field, and/or unrelated keys."""
    result = {}

    # For each alias→canonical pair, randomly decide what to include
    for alias, canonical in _FIELD_ALIASES.items():
        choice = draw(st.sampled_from(["alias_only", "canonical_only", "both", "neither"]))
        if choice == "alias_only":
            result[alias] = draw(_context_value_st)
        elif choice == "canonical_only":
            result[canonical] = draw(_context_value_st)
        elif choice == "both":
            result[alias] = draw(_context_value_st)
            result[canonical] = draw(_context_value_st)
        # "neither" — skip this pair

    # Add some unrelated keys
    extra = draw(st.dictionaries(
        keys=_non_alias_key_st,
        values=_context_value_st,
        max_size=5,
    ))
    result.update(extra)

    return result


# ---------------------------------------------------------------------------
# Property 2: Context name normalization produces only canonical names
# ---------------------------------------------------------------------------


class TestNormalizeContextNamesProperty:
    """Feature: plan-feature-refactoring, Property 2: Context name normalization
    produces only canonical names

    **Validates: Requirements 2.1**
    """

    @given(ctx=context_dict_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_alias_keys_remain_after_normalization(self, ctx: dict[str, Any]):
        """After normalization, no alias key from _FIELD_ALIASES remains in the result.

        Feature: plan-feature-refactoring, Property 2: Context name normalization produces only canonical names

        **Validates: Requirements 2.1**
        """
        result = normalize_context_names(ctx)

        for alias in _FIELD_ALIASES:
            assert alias not in result, (
                f"Alias key {alias!r} still present after normalization. "
                f"Input: {ctx!r}, Output: {result!r}"
            )

    @given(ctx=context_dict_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_values_preserved_under_canonical_names(self, ctx: dict[str, Any]):
        """All values from the input are preserved under their canonical key names.
        When both alias and canonical exist, the canonical value is kept.

        Feature: plan-feature-refactoring, Property 2: Context name normalization produces only canonical names

        **Validates: Requirements 2.1**
        """
        result = normalize_context_names(ctx)

        for alias, canonical in _FIELD_ALIASES.items():
            alias_present = alias in ctx
            canonical_present = canonical in ctx

            if canonical_present:
                # Canonical was in input — its value must be preserved
                assert result[canonical] == ctx[canonical], (
                    f"Canonical key {canonical!r} value changed. "
                    f"Expected {ctx[canonical]!r}, got {result[canonical]!r}"
                )
            elif alias_present:
                # Only alias was in input — value promoted to canonical
                assert canonical in result, (
                    f"Alias {alias!r} was present but canonical {canonical!r} "
                    f"is missing from result"
                )
                assert result[canonical] == ctx[alias], (
                    f"Alias value not promoted correctly. "
                    f"Expected {ctx[alias]!r} under {canonical!r}, "
                    f"got {result.get(canonical)!r}"
                )

    @given(ctx=context_dict_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_unrelated_keys_pass_through_unchanged(self, ctx: dict[str, Any]):
        """Keys that are neither aliases nor canonical names pass through unchanged.

        Feature: plan-feature-refactoring, Property 2: Context name normalization produces only canonical names

        **Validates: Requirements 2.1**
        """
        result = normalize_context_names(ctx)

        alias_keys = set(_FIELD_ALIASES.keys())
        canonical_keys = set(_FIELD_ALIASES.values())

        for key, value in ctx.items():
            if key not in alias_keys and key not in canonical_keys:
                assert key in result, (
                    f"Unrelated key {key!r} missing from result"
                )
                assert result[key] == value, (
                    f"Unrelated key {key!r} value changed. "
                    f"Expected {value!r}, got {result[key]!r}"
                )

    @given(ctx=context_dict_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_input_not_mutated(self, ctx: dict[str, Any]):
        """The original context dict is not mutated by normalization.

        Feature: plan-feature-refactoring, Property 2: Context name normalization produces only canonical names

        **Validates: Requirements 2.1**
        """
        original = dict(ctx)
        normalize_context_names(ctx)
        assert ctx == original, "normalize_context_names mutated the input dict"


# ---------------------------------------------------------------------------
# Unit Tests for build_context_items_summary()
# ---------------------------------------------------------------------------

from graph_kb_api.flows.v3.utils.context_utils import (
    _BULKY_CONTEXT_FIELDS,
    build_context_items_summary,
)


class TestBuildContextItemsSummary:
    """Unit tests for build_context_items_summary().

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
    """

    def test_empty_inputs_returns_empty_dict(self):
        """Empty research and context returns empty dict.

        **Validates: Requirements 3.1**
        """
        assert build_context_items_summary(None, {}, {}) == {}

    def test_bulky_fields_excluded(self):
        """All _BULKY_CONTEXT_FIELDS are stripped from output.

        **Validates: Requirements 3.3**
        """
        context: dict[str, Any] = {
            "spec_name": "my-spec",
            "uploaded_document_contents": [{"doc_id": "d1", "content": "huge..."}],
            "document_section_index": [{"doc_id": "d1", "sections": []}],
            "reference_documents": [{"url": "http://example.com", "content": "big"}],
            "deep_analysis_full": {"summary": "long analysis..."},
            "primary_document_id": "doc-123",
        }
        result = build_context_items_summary("sess-1", {}, context)

        for field in _BULKY_CONTEXT_FIELDS:
            assert field not in result, f"Bulky field {field!r} should be excluded"

        assert result["spec_name"] == "my-spec"
        assert result["primary_document_id"] == "doc-123"

    def test_non_bulky_fields_preserved(self):
        """Non-bulky context fields are preserved in output.

        **Validates: Requirements 3.5**
        """
        context: dict[str, Any] = {
            "spec_name": "test-spec",
            "user_explanation": "Build a widget",
            "primary_document_id": "doc-1",
            "supporting_doc_ids": ["doc-2", "doc-3"],
        }
        result = build_context_items_summary("sess-1", {}, context)

        assert result["spec_name"] == "test-spec"
        assert result["user_explanation"] == "Build a widget"
        assert result["primary_document_id"] == "doc-1"
        assert result["supporting_doc_ids"] == ["doc-2", "doc-3"]

    def test_research_doc_id_merged_into_supporting(self):
        """Research findings_doc_id is merged into supporting_doc_ids.

        **Validates: Requirements 3.2**
        """
        research: dict[str, Any] = {"findings_doc_id": "research-doc-1"}
        context: dict[str, Any] = {"supporting_doc_ids": ["doc-a"]}
        result = build_context_items_summary("sess-1", research, context)

        assert "research-doc-1" in result["supporting_doc_ids"]
        assert "doc-a" in result["supporting_doc_ids"]

    def test_research_doc_id_not_duplicated(self):
        """Research findings_doc_id is not duplicated if already present.

        **Validates: Requirements 3.2**
        """
        research: dict[str, Any] = {"findings_doc_id": "doc-a"}
        context: dict[str, Any] = {"supporting_doc_ids": ["doc-a"]}
        result = build_context_items_summary("sess-1", research, context)

        assert result["supporting_doc_ids"].count("doc-a") == 1

    def test_research_doc_id_creates_supporting_list(self):
        """Research findings_doc_id creates supporting_doc_ids if not present.

        **Validates: Requirements 3.2**
        """
        research: dict[str, Any] = {"findings_doc_id": "research-doc-1"}
        context: dict[str, Any] = {"spec_name": "test"}
        result = build_context_items_summary("sess-1", research, context)

        assert result["supporting_doc_ids"] == ["research-doc-1"]

    def test_none_context_with_research(self):
        """None context with research data still works.

        **Validates: Requirements 3.1**
        """
        research: dict[str, Any] = {"findings_doc_id": "r-1", "findings": {"key": "val"}}
        result = build_context_items_summary("sess-1", research, {})

        assert result["supporting_doc_ids"] == ["r-1"]

    def test_does_not_mutate_input(self):
        """The original context dict is not mutated.

        **Validates: Requirements 3.5**
        """
        context: dict[str, Any] = {
            "spec_name": "test",
            "uploaded_document_contents": [{"big": "data"}],
        }
        original = dict(context)
        build_context_items_summary("sess-1", {}, context)

        assert context == original

    def test_bulky_context_fields_frozenset_contents(self):
        """_BULKY_CONTEXT_FIELDS contains exactly the expected fields."""
        expected = {
            "uploaded_document_contents",
            "document_section_index",
            "reference_documents",
            "deep_analysis_full",
        }
        assert _BULKY_CONTEXT_FIELDS == expected


# ---------------------------------------------------------------------------
# Strategies for build_context_items_summary property tests
# ---------------------------------------------------------------------------

# Lightweight values suitable for context fields
_summary_value_st = st.one_of(
    st.text(max_size=30),
    st.integers(min_value=0, max_value=100),
    st.booleans(),
    st.lists(st.text(max_size=15), max_size=4),
)

# Keys that are NOT bulky fields (non-bulky context keys)
_non_bulky_key_st = st.text(min_size=1, max_size=30).filter(
    lambda k: k not in _BULKY_CONTEXT_FIELDS
    and k != "supporting_doc_ids"  # handled separately via research merge
)


@st.composite
def context_with_bulky_fields_st(draw):
    """Generate a context dict with a random mix of bulky and non-bulky fields."""
    result: dict[str, Any] = {}

    # Randomly include each bulky field
    for field in _BULKY_CONTEXT_FIELDS:
        if draw(st.booleans()):
            # Bulky fields typically hold large nested structures
            result[field] = draw(
                st.one_of(
                    st.lists(st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=2), max_size=3),
                    st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3),
                )
            )

    # Add non-bulky fields
    non_bulky = draw(
        st.dictionaries(keys=_non_bulky_key_st, values=_summary_value_st, min_size=0, max_size=6)
    )
    result.update(non_bulky)

    return result


@st.composite
def research_dict_st(draw):
    """Generate a research dict with optional findings_doc_id."""
    result: dict[str, Any] = {}
    if draw(st.booleans()):
        result["findings_doc_id"] = draw(st.text(min_size=1, max_size=20))
    # Optionally add other research fields
    if draw(st.booleans()):
        result["findings"] = draw(st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3))
    return result


# ---------------------------------------------------------------------------
# Property 3: Context items summary excludes bulky fields and matches
#              legacy output
# ---------------------------------------------------------------------------


class TestBuildContextItemsSummaryProperty:
    """Feature: plan-feature-refactoring, Property 3: Context items summary
    excludes bulky fields and matches legacy output

    **Validates: Requirements 3.3, 3.5**
    """

    @given(
        context=context_with_bulky_fields_st(),
        research=research_dict_st(),
        session_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_bulky_fields_in_output(
        self,
        context: dict[str, Any],
        research: dict[str, Any],
        session_id: str | None,
    ):
        """Output never contains any key from _BULKY_CONTEXT_FIELDS.

        Feature: plan-feature-refactoring, Property 3: Context items summary excludes bulky fields and matches legacy output

        **Validates: Requirements 3.3**
        """
        result = build_context_items_summary(session_id, research, context)

        for field in _BULKY_CONTEXT_FIELDS:
            assert field not in result, (
                f"Bulky field {field!r} found in output. "
                f"Context keys: {list(context.keys())!r}, "
                f"Output keys: {list(result.keys())!r}"
            )

    @given(
        context=context_with_bulky_fields_st(),
        research=research_dict_st(),
        session_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_non_bulky_fields_preserved(
        self,
        context: dict[str, Any],
        research: dict[str, Any],
        session_id: str | None,
    ):
        """Output contains all non-bulky context item fields from the input
        with their original values (except supporting_doc_ids which may be
        enriched by research merge).

        Feature: plan-feature-refactoring, Property 3: Context items summary excludes bulky fields and matches legacy output

        **Validates: Requirements 3.5**
        """
        result = build_context_items_summary(session_id, research, context)

        for key, value in context.items():
            if key in _BULKY_CONTEXT_FIELDS:
                continue  # bulky fields are excluded — tested above

            assert key in result, (
                f"Non-bulky key {key!r} missing from output. "
                f"Context keys: {list(context.keys())!r}, "
                f"Output keys: {list(result.keys())!r}"
            )

            # supporting_doc_ids may be enriched by research findings_doc_id merge
            if key == "supporting_doc_ids" and research.get("findings_doc_id"):
                # The original items must still be present
                for item in value if isinstance(value, list) else [value]:
                    assert item in result[key], (
                        f"Original supporting_doc_ids item {item!r} missing after merge"
                    )
            else:
                assert result[key] == value, (
                    f"Non-bulky key {key!r} value changed. "
                    f"Expected {value!r}, got {result[key]!r}"
                )
