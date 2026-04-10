"""Property-based tests for serialize_artifacts utility.

Tests the serialize_artifacts() standalone function that converts artifact
dictionaries to ArtifactManifestEntry lists for interrupt payloads.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.state.plan_state import ArtifactRef
from graph_kb_api.flows.v3.utils.artifact_utils import (
    _infer_content_type,
    serialize_artifacts,
)

# --- Strategies ---

# File extensions that map to known content types, plus some that fall through to text/plain
_EXTENSIONS = st.sampled_from([".json", ".md", ".jsonl", ".txt", ".py", ".csv", ""])

_SESSION_IDS = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=30,
)

_SHORT_KEYS = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_/"),
    min_size=1,
    max_size=40,
)


def _artifact_ref_strategy(extension: st.SearchStrategy[str] = _EXTENSIONS) -> st.SearchStrategy[ArtifactRef]:
    """Generate random ArtifactRef dicts with realistic key structures."""
    return st.builds(
        lambda session_id, short_key, ext, content_hash, size_bytes, created_at, summary: ArtifactRef(
            key=f"specs/{session_id}/{short_key}{ext}",
            content_hash=content_hash,
            size_bytes=size_bytes,
            created_at=created_at,
            summary=summary,
        ),
        session_id=_SESSION_IDS,
        short_key=_SHORT_KEYS,
        ext=extension,
        content_hash=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=8,
            max_size=64,
        ),
        size_bytes=st.integers(min_value=0, max_value=10_000_000),
        created_at=st.text(min_size=10, max_size=40),
        summary=st.text(min_size=0, max_size=200),
    )


_ARTIFACT_NAME = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_."),
    min_size=1,
    max_size=30,
)

_ARTIFACTS_DICT = st.dictionaries(
    keys=_ARTIFACT_NAME,
    values=_artifact_ref_strategy(),
    min_size=0,
    max_size=15,
)


class TestSerializeArtifactsProperty:
    """Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

    **Validates: Requirements 18.3**
    """

    @given(artifacts=_ARTIFACTS_DICT)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_output_length_matches_input(self, artifacts: dict[str, ArtifactRef]):
        """serialize_artifacts() returns a list with length equal to the input dict length.

        Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

        **Validates: Requirements 18.3**
        """
        entries = serialize_artifacts(artifacts)
        assert len(entries) == len(artifacts)

    @given(artifacts=_ARTIFACTS_DICT)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_entries_contain_required_fields(self, artifacts: dict[str, ArtifactRef]):
        """Each ArtifactManifestEntry contains key, content_type, summary, size_bytes, created_at.

        Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

        **Validates: Requirements 18.3**
        """
        entries = serialize_artifacts(artifacts)
        for entry in entries:
            assert "key" in entry
            assert "content_type" in entry
            assert "summary" in entry
            assert "size_bytes" in entry
            assert "created_at" in entry

    @given(artifacts=_ARTIFACTS_DICT)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_values_match_source_artifact_refs(self, artifacts: dict[str, ArtifactRef]):
        """Each entry's summary, size_bytes, and created_at match the corresponding ArtifactRef.

        Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

        **Validates: Requirements 18.3**
        """
        entries = serialize_artifacts(artifacts)
        refs = list(artifacts.values())
        for entry, ref in zip(entries, refs):
            assert entry["summary"] == ref["summary"]
            assert entry["size_bytes"] == ref["size_bytes"]
            assert entry["created_at"] == ref["created_at"]

    @given(artifacts=_ARTIFACTS_DICT)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_key_prefix_stripped(self, artifacts: dict[str, ArtifactRef]):
        """The specs/{session_id}/ prefix is stripped from each entry's key.

        Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

        **Validates: Requirements 18.3**
        """
        entries = serialize_artifacts(artifacts)
        for entry in entries:
            # After stripping, the key should not start with "specs/"
            assert not entry["key"].startswith("specs/")

    @given(artifacts=_ARTIFACTS_DICT)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_content_type_consistent_with_extension(self, artifacts: dict[str, ArtifactRef]):
        """content_type is inferred from the short key's file extension via _infer_content_type.

        Feature: plan-feature-refactoring, Property 14: serialize_artifacts handles all artifact types

        **Validates: Requirements 18.3**
        """
        entries = serialize_artifacts(artifacts)
        refs = list(artifacts.values())
        for entry, ref in zip(entries, refs):
            # Recompute the short key the same way the function does
            short_key = ref["key"]
            if "/" in short_key:
                short_key = short_key.split("/", 2)[-1]
            expected_ct = _infer_content_type(short_key)
            assert entry["content_type"] == expected_ct
