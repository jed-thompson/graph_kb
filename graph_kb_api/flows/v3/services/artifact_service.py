"""ArtifactService for coordinating blob storage access in the plan engine.

Provides store, retrieve, retrieve_json, exists operations with:
- SHA-256 content hashing for integrity verification
- Retry with exponential backoff (max 3 attempts)
- Path traversal validation
- Session-scoped key prefixing
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from graph_kb_api.flows.v3.state.plan_state import ArtifactRef
from graph_kb_api.storage.blob_storage import BlobStorage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ArtifactStorageError(Exception):
    """Raised when a blob storage operation fails after all retries."""

    pass


class ArtifactIntegrityError(Exception):
    """Raised when retrieved content hash does not match the expected hash."""

    pass


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

_UNSAFE_PATH_RE = re.compile(r"(^/|\.\.)")


def _validate_path_segment(value: str, label: str) -> None:
    """Reject namespace/name values that contain path traversal characters."""
    if _UNSAFE_PATH_RE.search(value):
        raise ValueError(f"{label} contains unsafe path characters: {value!r}")


# ---------------------------------------------------------------------------
# ArtifactService
# ---------------------------------------------------------------------------


class ArtifactService:
    """Coordinates all blob storage access for the plan engine.

    Bound to a single session at construction time.  Injected into LangGraph
    nodes via ``config["configurable"]["artifact_service"]``.
    """

    _MAX_RETRIES = 3
    _BASE_DELAY = 0.1  # seconds

    def __init__(self, blob_storage: BlobStorage, session_id: str) -> None:
        self.blob = blob_storage
        self.session_id = session_id

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    async def _retry_async(
        coro_factory, *, max_retries: int = _MAX_RETRIES, base_delay: float = _BASE_DELAY
    ):
        """Execute *coro_factory()* with exponential backoff.

        *coro_factory* is a zero-arg callable that returns a new awaitable each
        time (we cannot re-await the same coroutine on retry).

        Raises ``ArtifactStorageError`` wrapping the last exception after all
        retries are exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "Blob storage attempt %d/%d failed (%s), retrying in %.2fs",
                        attempt + 1,
                        max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise ArtifactStorageError(
            f"Blob storage operation failed after {max_retries} attempts"
        ) from last_exc

    # -- public API ---------------------------------------------------------

    async def store(
        self,
        namespace: str,
        name: str,
        content: str,
        summary: str,
        content_type: str = "application/json",
    ) -> ArtifactRef:
        """Persist *content* to blob storage and return a lightweight ref.

        The storage key follows the convention
        ``specs/{session_id}/{namespace}/{name}``.
        """
        _validate_path_segment(namespace, "namespace")
        _validate_path_segment(name, "name")

        key = f"specs/{self.session_id}/{namespace}/{name}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        size_bytes = len(content.encode())
        created_at = datetime.now(UTC).isoformat()

        await self._retry_async(lambda: self.blob.backend.store(key, content, content_type))

        return ArtifactRef(
            key=key,
            content_hash=content_hash,
            size_bytes=size_bytes,
            created_at=created_at,
            summary=summary,
        )

    async def retrieve(self, ref: ArtifactRef) -> str:
        """Return the full content string for *ref*.

        Raises ``FileNotFoundError`` if the artifact does not exist and
        ``ArtifactIntegrityError`` if the content hash does not match.
        """
        artifact = await self._retry_async(lambda: self.blob.backend.retrieve(ref["key"]))
        if artifact is None:
            raise FileNotFoundError(f"Artifact not found: {ref['key']}")

        # Integrity check
        raw = artifact.content
        actual_hash = hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()
        if actual_hash != ref["content_hash"]:
            raise ArtifactIntegrityError(
                f"Hash mismatch for {ref['key']}: "
                f"expected {ref['content_hash']}, got {actual_hash}"
            )

        return artifact.content

    async def retrieve_json(self, ref: ArtifactRef) -> dict:
        """Retrieve and JSON-parse the content for *ref*.

        Raises ``json.JSONDecodeError`` if the content is not valid JSON.
        """
        content = await self.retrieve(ref)
        return json.loads(content)

    async def exists(self, ref: ArtifactRef) -> bool:
        """Return ``True`` if the blob for *ref* exists."""
        return await self._retry_async(lambda: self.blob.backend.exists(ref["key"]))

    async def hydrate_artifacts(
        self,
        state: Dict[str, Any],
        namespace_prefix: str,
    ) -> Dict[str, str]:
        """Hydrate blob content for artifacts whose key starts with *namespace_prefix*.

        Scans ``state["artifacts"]`` and retrieves full content for every
        ``ArtifactRef`` whose ``key`` begins with
        ``specs/{session_id}/{namespace_prefix}``.

        Returns a mapping of artifact key → full content string.
        """
        artifacts: Dict[str, ArtifactRef] = state.get("artifacts", {})
        prefix = f"specs/{self.session_id}/{namespace_prefix}"

        result: Dict[str, str] = {}
        for _name, ref in artifacts.items():
            if ref["key"].startswith(prefix):
                content = await self.retrieve(ref)
                result[ref["key"]] = content
        return result
