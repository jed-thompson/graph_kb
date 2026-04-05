"""Property-based tests for ArtifactRef field correctness.

Property 4: Artifact Ref Field Correctness — For any content string stored
via ArtifactService.store(), the returned ArtifactRef should have
content_hash equal to SHA-256(content), size_bytes equal to
len(content.encode()), created_at parseable as ISO 8601, summary non-empty,
and key matching the pattern specs/{session_id}/{namespace}/{name}.

**Validates: Requirements 1.3, 1.4, 1.5, 1.6, 2.2**
"""

import hashlib
import re
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.state.plan_state import ArtifactRef

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_SESSION_ID_RE = r"[a-zA-Z0-9_-]{4,32}"
_NAMESPACE_RE = r"[a-z][a-z0-9_]{1,20}"
_NAME_RE = r"[a-z][a-z0-9_.]{1,30}"


@st.composite
def content_strategy(draw: st.DrawFn) -> str:
    """Generate arbitrary non-empty content strings."""
    return draw(st.text(min_size=1, max_size=500))


@st.composite
def summary_strategy(draw: st.DrawFn) -> str:
    """Generate non-empty summary strings (1-3 sentences)."""
    sentence = st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=5,
        max_size=80,
    )
    sentences = draw(st.lists(sentence, min_size=1, max_size=3))
    return ". ".join(sentences)


@st.composite
def artifact_ref_from_content(draw: st.DrawFn) -> tuple:
    """Generate a (content, ArtifactRef) pair simulating ArtifactService.store().

    Builds an ArtifactRef the same way ArtifactService.store() would:
    - key = specs/{session_id}/{namespace}/{name}
    - content_hash = SHA-256 hex digest of content
    - size_bytes = len(content.encode('utf-8'))
    - created_at = ISO 8601 timestamp
    - summary = non-empty string
    """
    session_id = draw(st.from_regex(_SESSION_ID_RE, fullmatch=True))
    namespace = draw(st.from_regex(_NAMESPACE_RE, fullmatch=True))
    name = draw(st.from_regex(_NAME_RE, fullmatch=True))
    content = draw(content_strategy())
    summary = draw(summary_strategy())

    key = f"specs/{session_id}/{namespace}/{name}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    size_bytes = len(content.encode("utf-8"))
    created_at = datetime.now(timezone.utc).isoformat()

    ref: ArtifactRef = {
        "key": key,
        "content_hash": content_hash,
        "size_bytes": size_bytes,
        "created_at": created_at,
        "summary": summary,
    }
    return content, ref


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestArtifactRefFieldCorrectness:
    """Property 4: Artifact Ref Field Correctness.

    For any content string stored via ArtifactService.store(), the returned
    ArtifactRef should have:
      - content_hash: 64-character SHA-256 hex string
      - size_bytes: non-negative integer equal to byte length of content
      - created_at: valid ISO 8601 timestamp
      - summary: non-empty string
      - key: matches pattern specs/{session_id}/{namespace}/{name}

    **Validates: Requirements 1.3, 1.4, 1.5, 1.6, 2.2**
    """

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_content_hash_is_64_char_hex(self, data):
        """content_hash must be a 64-character hexadecimal string (SHA-256)."""
        _content, ref = data
        assert len(ref["content_hash"]) == 64, (
            f"content_hash length is {len(ref['content_hash'])}, expected 64"
        )
        assert re.fullmatch(r"[0-9a-f]{64}", ref["content_hash"]), (
            f"content_hash is not a valid hex string: {ref['content_hash']}"
        )

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_content_hash_matches_sha256(self, data):
        """content_hash must equal SHA-256(content)."""
        content, ref = data
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert ref["content_hash"] == expected, (
            f"content_hash {ref['content_hash']} != SHA-256(content) {expected}"
        )

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_size_bytes_is_non_negative(self, data):
        """size_bytes must be a non-negative integer."""
        _content, ref = data
        assert isinstance(ref["size_bytes"], int)
        assert ref["size_bytes"] >= 0, f"size_bytes is negative: {ref['size_bytes']}"

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_size_bytes_equals_content_byte_length(self, data):
        """size_bytes must equal the byte length of the stored content."""
        content, ref = data
        expected = len(content.encode("utf-8"))
        assert ref["size_bytes"] == expected, (
            f"size_bytes {ref['size_bytes']} != len(content.encode()) {expected}"
        )

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_created_at_is_valid_iso8601(self, data):
        """created_at must be a valid ISO 8601 timestamp."""
        _content, ref = data
        try:
            parsed = datetime.fromisoformat(ref["created_at"])
            assert parsed is not None
        except (ValueError, TypeError) as exc:
            pytest.fail(
                f"created_at is not valid ISO 8601: {ref['created_at']!r} ({exc})"
            )

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_summary_is_non_empty(self, data):
        """summary must be a non-empty string."""
        _content, ref = data
        assert isinstance(ref["summary"], str)
        assert len(ref["summary"]) > 0, "summary must not be empty"

    @given(data=artifact_ref_from_content())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_key_matches_path_pattern(self, data):
        """key must match the pattern specs/{session_id}/{namespace}/{name}."""
        _content, ref = data
        pattern = r"^specs/[a-zA-Z0-9_-]+/[a-z][a-z0-9_]*/[a-z][a-z0-9_.]*$"
        assert re.fullmatch(pattern, ref["key"]), (
            f"key does not match expected pattern: {ref['key']!r}"
        )
