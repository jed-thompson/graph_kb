"""Property-based tests for DocumentManifest factory function.

Tests the create_empty_manifest() standalone function that produces
empty DocumentManifest dicts with correct default values.
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.state.plan_state import create_empty_manifest


class TestCreateEmptyManifestProperty:
    """Feature: plan-feature-refactoring, Property 9: DocumentManifest.create_empty()
    produces correct defaults

    **Validates: Requirements 9.3**
    """

    @given(
        session_id=st.text(min_size=0, max_size=200),
        spec_name=st.text(min_size=0, max_size=200),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_create_empty_manifest_defaults(self, session_id: str, spec_name: str):
        """For any session_id and spec_name strings, create_empty_manifest()
        returns a manifest with correct default field values and a valid
        ISO timestamp.

        Feature: plan-feature-refactoring, Property 9: DocumentManifest.create_empty() produces correct defaults

        **Validates: Requirements 9.3**
        """
        manifest = create_empty_manifest(session_id, spec_name)

        # session_id and spec_name are passed through
        assert manifest["session_id"] == session_id
        assert manifest["spec_name"] == spec_name

        # Default field values
        assert manifest["primary_spec_ref"] is None
        assert manifest["entries"] == []
        assert manifest["composed_index_ref"] is None
        assert manifest["total_documents"] == 0
        assert manifest["total_tokens"] == 0

        # created_at must be a non-empty ISO timestamp string
        assert isinstance(manifest["created_at"], str)
        assert len(manifest["created_at"]) > 0
        # Verify it parses as a valid ISO timestamp
        parsed = datetime.fromisoformat(manifest["created_at"])
        assert parsed.tzinfo is not None or "+" in manifest["created_at"] or "Z" in manifest["created_at"], (
            f"created_at should be timezone-aware: {manifest['created_at']!r}"
        )

        # finalized_at should be None for an empty manifest
        assert manifest["finalized_at"] is None
