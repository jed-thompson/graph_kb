"""Integration tests for ArtifactService: store → retrieve → verify hash integrity.

End-to-end tests using an in-memory blob backend that simulates real storage.
Validates the full lifecycle: store content, retrieve it, verify SHA-256 hash
matches, JSON round-trips, exists checks, and integrity error on tampered content.

**Validates: Requirements 2.1, 2.2, 3.1, 4.1, 4.2**
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from graph_kb_api.flows.v3.services.artifact_service import (
    ArtifactIntegrityError,
    ArtifactService,
)

# ---------------------------------------------------------------------------
# In-memory blob storage backend simulating real storage
# ---------------------------------------------------------------------------


@dataclass
class FakeArtifact:
    path: str
    content: str
    content_type: str
    size_bytes: int
    created_at: datetime
    metadata: Dict[str, Any]


class InMemoryBlobBackend:
    """In-memory blob backend that simulates a real storage backend."""

    def __init__(self):
        self._store: Dict[str, FakeArtifact] = {}

    async def store(
        self, path: str, content: str, content_type: str, metadata=None
    ) -> str:
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

    def tamper(self, path: str, new_content: str) -> None:
        """Directly mutate stored content to simulate corruption."""
        if path in self._store:
            artifact = self._store[path]
            self._store[path] = FakeArtifact(
                path=artifact.path,
                content=new_content,
                content_type=artifact.content_type,
                size_bytes=len(new_content.encode()),
                created_at=artifact.created_at,
                metadata=artifact.metadata,
            )


class FakeBlobStorage:
    """Mimics BlobStorage with a .backend attribute."""

    def __init__(self):
        self.backend = InMemoryBlobBackend()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SESSION_ID = "integration-test-session"


@pytest.fixture
def blob_storage():
    return FakeBlobStorage()


@pytest.fixture
def service(blob_storage):
    return ArtifactService(blob_storage, SESSION_ID)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestStoreRetrieveHashIntegrity:
    """Store content, retrieve it, verify SHA-256 hash matches ref.content_hash."""

    @pytest.mark.asyncio
    async def test_store_retrieve_hash_matches(self, service):
        content = "This is integration test content for hash verification."
        ref = await service.store(
            "research", "findings.json", content, "Research findings"
        )

        retrieved = await service.retrieve(ref)

        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        assert ref["content_hash"] == expected_hash
        assert hashlib.sha256(retrieved.encode()).hexdigest() == ref["content_hash"]

    @pytest.mark.asyncio
    async def test_hash_is_64_char_hex(self, service):
        ref = await service.store("context", "data.txt", "some data", "Context data")

        assert len(ref["content_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in ref["content_hash"])


class TestStoreRetrieveJsonRoundTrip:
    """Store JSON content, retrieve via retrieve_json, verify parsed dict matches."""

    @pytest.mark.asyncio
    async def test_json_round_trip(self, service):
        data = {
            "tasks": [
                {"id": 1, "name": "Implement feature"},
                {"id": 2, "name": "Write tests"},
            ],
            "metadata": {"version": "1.0", "count": 42},
        }
        content = json.dumps(data)
        ref = await service.store(
            "planning", "roadmap.json", content, "Planning roadmap"
        )

        result = await service.retrieve_json(ref)

        assert result == data

    @pytest.mark.asyncio
    async def test_json_with_nested_structures(self, service):
        data = {"nested": {"deep": {"value": [1, 2, 3], "flag": True}}, "top": None}
        content = json.dumps(data)
        ref = await service.store(
            "assembly", "structure.json", content, "Nested structure"
        )

        result = await service.retrieve_json(ref)

        assert result == data


class TestStoreExistsIntegration:
    """Store content, verify exists returns True."""

    @pytest.mark.asyncio
    async def test_exists_true_after_store(self, service):
        ref = await service.store("orchestrate", "draft.md", "# Draft", "Task draft")

        assert await service.exists(ref) is True

    @pytest.mark.asyncio
    async def test_exists_false_for_unstored(self, service):
        fake_ref = {
            "key": f"specs/{SESSION_ID}/nonexistent/file.txt",
            "content_hash": "a" * 64,
            "size_bytes": 0,
            "created_at": "2024-01-01T00:00:00",
            "summary": "Does not exist",
        }

        assert await service.exists(fake_ref) is False


class TestTamperedContentIntegrity:
    """Retrieve tampered content raises ArtifactIntegrityError."""

    @pytest.mark.asyncio
    async def test_tampered_content_raises_integrity_error(self, service, blob_storage):
        original = "Original untampered content"
        ref = await service.store(
            "research", "results.json", original, "Research results"
        )

        # Tamper with the stored content directly in the backend
        blob_storage.backend.tamper(ref["key"], "TAMPERED CONTENT")

        with pytest.raises(ArtifactIntegrityError):
            await service.retrieve(ref)

    @pytest.mark.asyncio
    async def test_tampered_content_error_message_includes_hashes(
        self, service, blob_storage
    ):
        original = "Content before tampering"
        ref = await service.store("context", "analysis.txt", original, "Analysis")

        blob_storage.backend.tamper(ref["key"], "Modified by attacker")

        with pytest.raises(ArtifactIntegrityError, match="Hash mismatch"):
            await service.retrieve(ref)


class TestStoreRetrieveRoundTripPreservesContent:
    """Store → retrieve round-trip preserves content exactly."""

    @pytest.mark.asyncio
    async def test_plain_text_preserved(self, service):
        content = "Hello, world! Special chars: é, ñ, ü, 中文, 🎉"
        ref = await service.store("output", "spec.md", content, "Final spec")

        retrieved = await service.retrieve(ref)

        assert retrieved == content

    @pytest.mark.asyncio
    async def test_multiline_content_preserved(self, service):
        content = "Line 1\nLine 2\n\nLine 4 with\ttabs\nLine 5"
        ref = await service.store("audit", "log.txt", content, "Audit log")

        retrieved = await service.retrieve(ref)

        assert retrieved == content

    @pytest.mark.asyncio
    async def test_large_content_preserved(self, service):
        content = "x" * 100_000
        ref = await service.store("orchestrate", "large.txt", content, "Large artifact")

        retrieved = await service.retrieve(ref)

        assert retrieved == content
        assert ref["size_bytes"] == len(content.encode())
