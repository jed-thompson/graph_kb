"""Unit tests for ArtifactService.

Covers store, retrieve, retrieve_json, exists, integrity checks,
retry logic, path validation, and hydrate_artifacts utility.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import pytest

from graph_kb_api.flows.v3.services.artifact_service import (
    ArtifactIntegrityError,
    ArtifactService,
    ArtifactStorageError,
)
from graph_kb_api.storage.blob_storage import Artifact, BlobStorage, BlobStorageBackend

# ---------------------------------------------------------------------------
# Fake blob storage backend
# ---------------------------------------------------------------------------


class FakeBlobBackend(BlobStorageBackend):
    """In-memory blob backend for testing."""

    def __init__(self):
        self._store: Dict[str, Artifact] = {}

    async def store(
        self, path: str, content: str | bytes, content_type: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        self._store[path] = Artifact(
            path=path,
            content=content,
            content_type=content_type,
            size_bytes=len(content.encode() if isinstance(content, str) else content),
            created_at=datetime.now(UTC),
            metadata=metadata or {},
        )
        return path

    async def retrieve(self, path: str) -> Optional[Artifact]:
        return self._store.get(path)

    async def exists(self, path: str) -> bool:
        return path in self._store

    async def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    async def list_directory(self, prefix: str) -> List[str]:
        return [p for p in self._store if p.startswith(prefix)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SESSION_ID = "test-session-123"


@pytest.fixture
def blob_storage():
    return BlobStorage(FakeBlobBackend())


@pytest.fixture
def service(blob_storage):
    return ArtifactService(blob_storage, SESSION_ID)


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class TestStore:
    @pytest.mark.asyncio
    async def test_returns_artifact_ref_with_correct_key(self, service):
        ref = await service.store(
            "research", "web_results.json", '{"data": 1}', "Web results"
        )
        assert ref["key"] == f"specs/{SESSION_ID}/research/web_results.json"

    @pytest.mark.asyncio
    async def test_content_hash_is_sha256(self, service):
        content = '{"hello": "world"}'
        ref = await service.store("ns", "name.json", content, "summary")
        expected = hashlib.sha256(content.encode()).hexdigest()
        assert ref["content_hash"] == expected
        assert len(ref["content_hash"]) == 64

    @pytest.mark.asyncio
    async def test_size_bytes_matches_encoded_length(self, service):
        content = "hello 🌍"
        ref = await service.store("ns", "f.txt", content, "summary", "text/plain")
        assert ref["size_bytes"] == len(content.encode())

    @pytest.mark.asyncio
    async def test_created_at_is_iso_format(self, service):
        ref = await service.store("ns", "f.json", "{}", "summary")
        # Should parse without error
        datetime.fromisoformat(ref["created_at"])

    @pytest.mark.asyncio
    async def test_summary_preserved(self, service):
        ref = await service.store("ns", "f.json", "{}", "My summary text")
        assert ref["summary"] == "My summary text"

    @pytest.mark.asyncio
    async def test_content_type_passed_to_backend(self, blob_storage, service):
        await service.store("ns", "f.md", "# Hello", "summary", "text/markdown")
        artifact = await blob_storage.backend.retrieve(f"specs/{SESSION_ID}/ns/f.md")
        assert artifact.content_type == "text/markdown"


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    @pytest.mark.asyncio
    async def test_round_trip(self, service):
        content = '{"key": "value"}'
        ref = await service.store("ns", "data.json", content, "summary")
        result = await service.retrieve(ref)
        assert result == content

    @pytest.mark.asyncio
    async def test_missing_raises_file_not_found(self, service):
        ref = {
            "key": "specs/nonexistent/path",
            "content_hash": "abc",
            "size_bytes": 0,
            "created_at": "",
            "summary": "",
        }
        with pytest.raises(FileNotFoundError):
            await service.retrieve(ref)

    @pytest.mark.asyncio
    async def test_integrity_error_on_hash_mismatch(self, service, blob_storage):
        content = "original"
        ref = await service.store("ns", "f.txt", content, "summary", "text/plain")
        # Tamper with stored content
        blob_storage.backend._store[ref["key"]].content = "tampered"
        with pytest.raises(ArtifactIntegrityError):
            await service.retrieve(ref)


# ---------------------------------------------------------------------------
# retrieve_json
# ---------------------------------------------------------------------------


class TestRetrieveJson:
    @pytest.mark.asyncio
    async def test_returns_parsed_dict(self, service):
        data = {"items": [1, 2, 3], "nested": {"a": True}}
        ref = await service.store("ns", "data.json", json.dumps(data), "summary")
        result = await service.retrieve_json(ref)
        assert result == data

    @pytest.mark.asyncio
    async def test_invalid_json_raises_decode_error(self, service):
        ref = await service.store(
            "ns", "bad.json", "not json {{{", "summary", "text/plain"
        )
        with pytest.raises(json.JSONDecodeError):
            await service.retrieve_json(ref)


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    @pytest.mark.asyncio
    async def test_true_after_store(self, service):
        ref = await service.store("ns", "f.json", "{}", "summary")
        assert await service.exists(ref) is True

    @pytest.mark.asyncio
    async def test_false_for_missing(self, service):
        ref = {
            "key": "specs/missing/path",
            "content_hash": "",
            "size_bytes": 0,
            "created_at": "",
            "summary": "",
        }
        assert await service.exists(ref) is False


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


class TestPathValidation:
    @pytest.mark.asyncio
    async def test_rejects_dotdot_in_namespace(self, service):
        with pytest.raises(ValueError, match="namespace"):
            await service.store("../etc", "f.json", "{}", "summary")

    @pytest.mark.asyncio
    async def test_rejects_dotdot_in_name(self, service):
        with pytest.raises(ValueError, match="name"):
            await service.store("ns", "../secret.json", "{}", "summary")

    @pytest.mark.asyncio
    async def test_rejects_leading_slash_in_namespace(self, service):
        with pytest.raises(ValueError, match="namespace"):
            await service.store("/absolute", "f.json", "{}", "summary")

    @pytest.mark.asyncio
    async def test_rejects_leading_slash_in_name(self, service):
        with pytest.raises(ValueError, match="name"):
            await service.store("ns", "/f.json", "{}", "summary")

    @pytest.mark.asyncio
    async def test_allows_nested_namespace(self, service):
        ref = await service.store(
            "orchestrate/tasks/t1", "draft.md", "content", "summary", "text/markdown"
        )
        assert "orchestrate/tasks/t1" in ref["key"]


# ---------------------------------------------------------------------------
# Retry / ArtifactStorageError
# ---------------------------------------------------------------------------


class FlakyFakeBlobBackend(FakeBlobBackend):
    """Backend that fails the first N store attempts before succeeding."""

    def __init__(self, failures_before_success: int = 2):
        super().__init__()
        self.failures_before_success = failures_before_success
        self.call_count = 0

    async def store(
        self,
        path: str,
        content: str | bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.call_count += 1
        if self.call_count <= self.failures_before_success:
            raise ConnectionError("transient")
        return await super().store(path, content, content_type, metadata)


class AlwaysFailFakeBlobBackend(FakeBlobBackend):
    """Backend that always fails on store."""

    async def store(
        self,
        path: str,
        content: str | bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        raise ConnectionError("permanent")


class TestRetry:
    @pytest.mark.asyncio
    async def test_store_retries_on_failure(self):
        backend = FlakyFakeBlobBackend(failures_before_success=2)
        storage = BlobStorage(backend)
        svc = ArtifactService(storage, SESSION_ID)

        ref = await svc.store("ns", "f.json", "{}", "summary")
        assert ref["key"] == f"specs/{SESSION_ID}/ns/f.json"
        assert backend.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_storage_error_after_max_retries(self):
        backend = AlwaysFailFakeBlobBackend()
        storage = BlobStorage(backend)
        svc = ArtifactService(storage, SESSION_ID)

        with pytest.raises(ArtifactStorageError):
            await svc.store("ns", "f.json", "{}", "summary")


# ---------------------------------------------------------------------------
# hydrate_artifacts
# ---------------------------------------------------------------------------


class TestHydrateArtifacts:
    @pytest.mark.asyncio
    async def test_hydrates_matching_prefix(self, service):
        ref1 = await service.store("research", "web.json", '{"a":1}', "web")
        ref2 = await service.store("research", "vec.json", '{"b":2}', "vec")
        ref3 = await service.store("planning", "roadmap.json", '{"c":3}', "roadmap")

        state = {
            "artifacts": {
                "research.web": ref1,
                "research.vec": ref2,
                "planning.roadmap": ref3,
            }
        }
        result = await service.hydrate_artifacts(state, "research")

        assert len(result) == 2
        assert result[ref1["key"]] == '{"a":1}'
        assert result[ref2["key"]] == '{"b":2}'
        assert ref3["key"] not in result

    @pytest.mark.asyncio
    async def test_empty_when_no_match(self, service):
        ref = await service.store("research", "web.json", "{}", "web")
        state = {"artifacts": {"research.web": ref}}
        result = await service.hydrate_artifacts(state, "planning")
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_state(self, service):
        result = await service.hydrate_artifacts({}, "research")
        assert result == {}
