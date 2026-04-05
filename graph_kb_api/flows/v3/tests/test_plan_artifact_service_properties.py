"""Property-based tests for ArtifactService.

Property 1: Artifact Store/Retrieve Round-Trip — For any content string,
storing it and then retrieving it should return the exact same content, and
the content_hash of the retrieved content should match the ref's content_hash.

Property 2: Artifact JSON Round-Trip — For any JSON-serializable dict,
storing it as JSON and retrieving via retrieve_json should return the same dict.

Property 3: Artifact Key Path Convention — For any valid namespace and name,
the returned ArtifactRef key must match ``specs/{session_id}/{namespace}/{name}``.

Property 5: Artifact Exists After Store — After storing any content,
exists(ref) must return True.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.services.artifact_service import ArtifactService

# ---------------------------------------------------------------------------
# Fake blob storage backend (same pattern as test_artifact_service.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeArtifact:
    path: str
    content: str
    content_type: str
    size_bytes: int
    created_at: datetime
    metadata: Dict[str, Any]


class FakeBlobBackend:
    """In-memory blob backend matching BlobStorageBackend interface."""

    def __init__(self):
        self._store: Dict[str, FakeArtifact] = {}

    async def store(self, path: str, content: str, content_type: str, metadata=None) -> str:
        self._store[path] = FakeArtifact(
            path=path,
            content=content,
            content_type=content_type,
            size_bytes=len(content.encode()),
            created_at=datetime.now(),
            metadata=metadata or {},
        )
        return path

    async def retrieve(self, path: str) -> Optional[FakeArtifact]:
        return self._store.get(path)

    async def exists(self, path: str) -> bool:
        return path in self._store

    async def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    async def list_directory(self, prefix: str) -> List[str]:
        return [p for p in self._store if p.startswith(prefix)]


class FakeBlobStorage:
    """Mimics BlobStorage with a .backend attribute."""

    def __init__(self):
        self.backend = FakeBlobBackend()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

SESSION_ID = "prop-test-session"

namespace_st = st.from_regex(r"[a-z][a-z0-9_]{1,20}", fullmatch=True)
# Avoid consecutive dots (..) which triggers path traversal validation.
# Use segments of [a-z0-9_]+ separated by single dots.
name_st = st.from_regex(r"[a-z][a-z0-9_]{0,10}(\.[a-z0-9_]+){0,3}", fullmatch=True)
content_st = st.text(min_size=1, max_size=500)
summary_st = st.text(min_size=1, max_size=100)
json_data_st = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(
        st.integers(),
        st.text(min_size=0, max_size=20),
        st.booleans(),
        st.none(),
    ),
    min_size=1,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> ArtifactService:
    return ArtifactService(cast(Any, FakeBlobStorage()), SESSION_ID)


# ---------------------------------------------------------------------------
# Property 1: Artifact Store/Retrieve Round-Trip
# ---------------------------------------------------------------------------


class TestArtifactStoreRetrieveRoundTrip:
    """Property 1: Artifact Store/Retrieve Round-Trip

    For any content string, storing it and then retrieving it should return
    the exact same content. The content_hash of the retrieved content should
    match the ref's content_hash.

    **Validates: Requirements 2.1, 3.1, 4.1**
    """

    @given(namespace=namespace_st, name=name_st, content=content_st, summary=summary_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_round_trip_content_preserved(
        self, namespace, name, content, summary
    ):
        """Stored content is identical when retrieved."""
        svc = _make_service()
        ref = await svc.store(namespace, name, content, summary)
        retrieved = await svc.retrieve(ref)
        assert retrieved == content

    @given(namespace=namespace_st, name=name_st, content=content_st, summary=summary_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_round_trip_hash_matches(self, namespace, name, content, summary):
        """The ref's content_hash matches SHA-256 of the stored content."""
        svc = _make_service()
        ref = await svc.store(namespace, name, content, summary)
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        assert ref["content_hash"] == expected_hash


# ---------------------------------------------------------------------------
# Property 2: Artifact JSON Round-Trip
# ---------------------------------------------------------------------------


class TestArtifactJsonRoundTrip:
    """Property 2: Artifact JSON Round-Trip

    For any JSON-serializable dict, storing it as JSON and retrieving via
    retrieve_json should return the same dict.

    **Validates: Requirement 3.3**
    """

    @given(namespace=namespace_st, name=name_st, data=json_data_st, summary=summary_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_json_round_trip(self, namespace, name, data, summary):
        """JSON-serializable dicts survive store → retrieve_json."""
        svc = _make_service()
        ref = await svc.store(namespace, name, json.dumps(data), summary)
        result = await svc.retrieve_json(ref)
        assert result == data


# ---------------------------------------------------------------------------
# Property 3: Artifact Key Path Convention
# ---------------------------------------------------------------------------


class TestArtifactKeyPathConvention:
    """Property 3: Artifact Key Path Convention

    For any valid namespace and name, the returned ArtifactRef key must match
    ``specs/{session_id}/{namespace}/{name}``.

    **Validates: Requirements 1.2, 5.2, 26.1**
    """

    @given(namespace=namespace_st, name=name_st, content=content_st, summary=summary_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_key_follows_convention(self, namespace, name, content, summary):
        """ArtifactRef key matches specs/{session_id}/{namespace}/{name}."""
        svc = _make_service()
        ref = await svc.store(namespace, name, content, summary)
        expected_key = f"specs/{SESSION_ID}/{namespace}/{name}"
        assert ref["key"] == expected_key


# ---------------------------------------------------------------------------
# Property 5: Artifact Exists After Store
# ---------------------------------------------------------------------------


class TestArtifactExistsAfterStore:
    """Property 5: Artifact Exists After Store

    After storing any content, exists(ref) must return True.

    **Validates: Requirements 2.3, 3.5**
    """

    @given(namespace=namespace_st, name=name_st, content=content_st, summary=summary_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_exists_true_after_store(self, namespace, name, content, summary):
        """exists(ref) returns True immediately after store."""
        svc = _make_service()
        ref = await svc.store(namespace, name, content, summary)
        assert await svc.exists(ref) is True
