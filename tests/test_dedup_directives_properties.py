"""Property-based tests for dedup directive validation.

Property 8: For any set of dedup directives and a document manifest,
            after validation, canonical_section and all duplicate_in entries
            reference task IDs present in the manifest, and each directive
            has topic and action fields.

**Validates: Requirements 8.2, 8.3**
"""

from __future__ import annotations

import os
import sys

from hypothesis import given, settings, HealthCheck, strategies as st

# Import standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "graph_kb_api",
    "flows",
    "v3",
    "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))

from dedup_directives import validate_dedup_directives  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

task_id_st = st.from_regex(r"task_[0-9]{3}", fullmatch=True)

manifest_ids_st = st.frozensets(task_id_st, min_size=1, max_size=20).map(set)

topic_st = st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))
action_st = st.text(min_size=1, max_size=120, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))


@st.composite
def valid_directive_st(draw: st.DrawFn, manifest_ids: set[str]):
    """Generate a directive whose IDs are all drawn from *manifest_ids*."""
    ids = sorted(manifest_ids)
    canonical = draw(st.sampled_from(ids))
    others = [i for i in ids if i != canonical]
    if not others:
        # Need at least one duplicate_in entry; reuse canonical as fallback
        dup_in = [canonical]
    else:
        dup_in = draw(st.lists(st.sampled_from(others), min_size=1, max_size=min(5, len(others))))
    return {
        "canonical_section": canonical,
        "duplicate_in": dup_in,
        "topic": draw(topic_st),
        "action": draw(action_st),
    }


@st.composite
def maybe_invalid_directive_st(draw: st.DrawFn, manifest_ids: set[str]):
    """Generate a directive that may or may not be valid."""
    # 50% chance of a valid directive, 50% chance of something potentially invalid
    if draw(st.booleans()):
        return draw(valid_directive_st(manifest_ids))
    else:
        # Possibly invalid: may reference IDs outside manifest
        all_ids = sorted(manifest_ids) + ["unknown_001", "unknown_002", "missing_task"]
        canonical = draw(st.sampled_from(all_ids))
        dup_in = draw(st.lists(st.sampled_from(all_ids), min_size=0, max_size=5))
        topic = draw(st.one_of(topic_st, st.just("")))
        action = draw(st.one_of(action_st, st.just("")))
        return {
            "canonical_section": canonical,
            "duplicate_in": dup_in,
            "topic": topic,
            "action": action,
        }


@st.composite
def directives_and_manifest_st(draw: st.DrawFn):
    """Generate a (raw_directives, manifest_task_ids) pair."""
    manifest_ids = draw(manifest_ids_st)
    directives = draw(st.lists(maybe_invalid_directive_st(manifest_ids), min_size=0, max_size=15))
    return directives, manifest_ids


# ---------------------------------------------------------------------------
# Property 8: Dedup directive validity
# ---------------------------------------------------------------------------


class TestDedupDirectiveValidity:
    """Property 8: Dedup directive validity.

    **Validates: Requirements 8.2, 8.3**
    """

    @given(data=directives_and_manifest_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_validated_canonical_section_in_manifest(self, data: tuple):
        """After validation, every canonical_section references a manifest task ID.

        **Validates: Requirement 8.3**
        """
        raw_directives, manifest_ids = data
        result = validate_dedup_directives(raw_directives, manifest_ids)
        for d in result:
            assert d["canonical_section"] in manifest_ids, (
                f"canonical_section '{d['canonical_section']}' not in manifest {manifest_ids}"
            )

    @given(data=directives_and_manifest_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_validated_duplicate_in_entries_in_manifest(self, data: tuple):
        """After validation, every duplicate_in entry references a manifest task ID.

        **Validates: Requirement 8.3**
        """
        raw_directives, manifest_ids = data
        result = validate_dedup_directives(raw_directives, manifest_ids)
        for d in result:
            for dup_id in d["duplicate_in"]:
                assert dup_id in manifest_ids, (
                    f"duplicate_in entry '{dup_id}' not in manifest {manifest_ids}"
                )

    @given(data=directives_and_manifest_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_validated_directives_have_topic_and_action(self, data: tuple):
        """After validation, every directive has non-empty topic and action fields.

        **Validates: Requirement 8.2**
        """
        raw_directives, manifest_ids = data
        result = validate_dedup_directives(raw_directives, manifest_ids)
        for d in result:
            assert d["topic"], f"Directive has empty topic: {d}"
            assert d["action"], f"Directive has empty action: {d}"

    @given(data=directives_and_manifest_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_validated_directives_have_nonempty_duplicate_in(self, data: tuple):
        """After validation, every directive has a non-empty duplicate_in list.

        **Validates: Requirement 8.2**
        """
        raw_directives, manifest_ids = data
        result = validate_dedup_directives(raw_directives, manifest_ids)
        for d in result:
            assert len(d["duplicate_in"]) > 0, (
                f"Directive has empty duplicate_in: {d}"
            )

    @given(data=directives_and_manifest_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_directives_count_leq_input(self, data: tuple):
        """The number of validated directives never exceeds the input count.

        **Validates: Requirements 8.2, 8.3**
        """
        raw_directives, manifest_ids = data
        result = validate_dedup_directives(raw_directives, manifest_ids)
        assert len(result) <= len(raw_directives)
