"""Blob storage abstraction for workflow artifacts.

Provides a unified interface for storing and retrieving artifacts:
- Full specification documents (Markdown)
- Story cards (individual Markdown files)
- Dependency visualizations (Mermaid)

Supports multiple backends:
- Local filesystem (development)
- S3-compatible storage (production)
- Azure Blob Storage (production)

Configuration via environment variables:
- SPEC_STORAGE_BACKEND: "local", "s3", or "azure" (default: "local")
- SPEC_STORAGE_PATH: Local path for filesystem storage
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET for S3
- AZURE_STORAGE_CONNECTION_STRING, AZURE_CONTAINER_NAME for Azure
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aioboto3
from azure.storage.blob.aio import BlobServiceClient

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


@dataclass
class Artifact:
    """Represents a stored artifact."""

    path: str
    content: str | bytes
    content_type: str
    size_bytes: int
    created_at: datetime
    metadata: Dict[str, Any]


class BlobStorageBackend(ABC):
    """Abstract base class for blob storage backends."""

    @abstractmethod
    async def store(
        self, path: str, content: str | bytes, content_type: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Store content at path. Returns the storage path."""
        pass

    @abstractmethod
    async def retrieve(self, path: str) -> Optional[Artifact]:
        """Retrieve content from path. Returns None if not found."""
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete content at path. Returns True if deleted."""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if content exists at path."""
        pass

    @abstractmethod
    async def list_directory(self, prefix: str) -> List[str]:
        """List all paths under prefix."""
        pass

    async def generate_presigned_url(self, path: str, expires_in: int = 3600) -> str:
        """Generate a pre-signed URL for direct access.

        Not all backends support this. Default raises NotImplementedError.
        """
        raise NotImplementedError(f"Pre-signed URLs not supported by {type(self).__name__}")

    # =========================================================================
    # Binary content methods (for file uploads)
    # =========================================================================

    async def store_binary(
        self,
        path: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store binary content at path. Returns the storage path.

        Default implementation encodes bytes as UTF-8 for text-based storage.
        Subclasses should override for native binary support.
        """
        # Default: try to decode as text and use text storage
        try:
            text_content = content.decode("utf-8")
            return await self.store(path, text_content, content_type, metadata)
        except UnicodeDecodeError:
            raise ValueError(
                "Binary content not supported by this backend. Use a backend with native binary support (S3, Azure)."
            )

    async def retrieve_binary(self, path: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """Retrieve binary content from path. Returns (content, metadata) or None.

        Default implementation retrieves text and encodes as UTF-8.
        Subclasses should override for native binary support.
        """
        artifact = await self.retrieve(path)
        if artifact is None:
            return None
        raw = artifact.content
        return (raw.encode("utf-8") if isinstance(raw, str) else raw, artifact.metadata)


class LocalFilesystemBackend(BlobStorageBackend):
    """Local filesystem storage backend for development.

    Stores files under a configured base path with structure:
    {base_path}/
        specs/
            {session_id}/
                spec.md
                stories/
                    story-1.md
                    story-2.md
                diagrams/
                    dependencies.mmd
    """

    def __init__(self, base_path: str = "./spec_artifacts"):
        """Initialize with base path for storage.

        Args:
            base_path: Root directory for artifact storage.
        """
        self.base_path = Path(base_path)
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure base directories exist."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "specs").mkdir(exist_ok=True)

    def _get_full_path(self, path: str) -> Path:
        """Get full filesystem path from relative path."""
        return self.base_path / path

    async def store(
        self,
        path: str,
        content: str | bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store content at path.

        Accepts both ``str`` (text artifacts) and ``bytes`` (binary files
        such as PDFs, Word docs, images).  The caller is responsible for
        providing the correct *content_type*.
        """
        full_path = self._get_full_path(path)

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content — use write_bytes for binary, write_text for text
        if isinstance(content, bytes):
            full_path.write_bytes(content)
        else:
            full_path.write_text(content, encoding="utf-8")

        # Write metadata alongside if provided
        if metadata:
            meta_path = full_path.with_suffix(full_path.suffix + ".meta.json")
            meta_path.write_text(json.dumps(metadata, default=str), encoding="utf-8")

        logger.debug(f"Stored artifact at {path} ({len(content)} bytes)")
        return path

    async def retrieve(self, path: str) -> Optional[Artifact]:
        """Retrieve content from path."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            return None

        # Read content — try text first, fall back to binary
        try:
            content: str | bytes = full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = full_path.read_bytes()
        stat = full_path.stat()

        # Load metadata if exists
        metadata = {}
        meta_path = full_path.with_suffix(full_path.suffix + ".meta.json")
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Determine content type
        content_type = "text/markdown"
        if path.endswith(".mmd"):
            content_type = "text/vnd.mermaid"
        elif path.endswith(".json"):
            content_type = "application/json"

        return Artifact(
            path=path,
            content=content,
            content_type=content_type,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
            metadata=metadata,
        )

    async def delete(self, path: str) -> bool:
        """Delete content at path."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            return False

        full_path.unlink()

        # Also delete metadata file if exists
        meta_path = full_path.with_suffix(full_path.suffix + ".meta.json")
        if meta_path.exists():
            meta_path.unlink()

        logger.debug(f"Deleted artifact at {path}")
        return True

    async def exists(self, path: str) -> bool:
        """Check if content exists at path."""
        return self._get_full_path(path).exists()

    async def list_directory(self, prefix: str) -> List[str]:
        """List all paths under prefix."""
        full_prefix = self._get_full_path(prefix)

        if not full_prefix.exists():
            return []

        paths = []
        for file_path in full_prefix.rglob("*"):
            if file_path.is_file() and not file_path.suffix.endswith(".meta.json"):
                rel_path = file_path.relative_to(self.base_path)
                paths.append(str(rel_path).replace("\\", "/"))

        return sorted(paths)

    # =========================================================================
    # Binary content methods (native filesystem support)
    # =========================================================================

    async def store_binary(
        self,
        path: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store binary content at path."""
        full_path = self._get_full_path(path)

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write binary content
        full_path.write_bytes(content)

        # Write metadata alongside if provided
        if metadata:
            meta_path = full_path.with_suffix(full_path.suffix + ".meta.json")
            meta_path.write_text(json.dumps(metadata, default=str), encoding="utf-8")

        logger.debug(f"Stored binary artifact at {path} ({len(content)} bytes)")
        return path

    async def retrieve_binary(self, path: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """Retrieve binary content from path."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            return None

        content = full_path.read_bytes()

        # Load metadata if exists
        metadata = {}
        meta_path = full_path.with_suffix(full_path.suffix + ".meta.json")
        if meta_path.exists():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        return (content, metadata)


class S3Backend(BlobStorageBackend):
    """S3-compatible storage backend for production.

    Uses aioboto3 for async operations.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "specs",
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None,
    ):
        """Initialize S3 backend.

        Args:
            bucket: S3 bucket name.
            prefix: Key prefix for all artifacts.
            region: AWS region.
            endpoint_url: Optional custom endpoint (for S3-compatible services).
        """
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.endpoint_url = endpoint_url
        self._client = None

    async def _get_client(self):
        """Get or create S3 client."""
        if self._client is None:
            try:
                session = aioboto3.Session()
                self._client = session.client(
                    "s3",
                    region_name=self.region,
                    endpoint_url=self.endpoint_url,
                )
            except ImportError:
                raise RuntimeError("aioboto3 is required for S3 storage backend")
        return self._client

    def _get_key(self, path: str) -> str:
        """Get full S3 key from relative path."""
        return f"{self.prefix}/{path}"

    async def store(
        self,
        path: str,
        content: str | bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store content in S3."""
        client = await self._get_client()
        key = self._get_key(path)

        extra_args = {
            "ContentType": content_type,
        }

        if metadata:
            # S3 metadata must be strings
            extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}

        async with client as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content.encode("utf-8"),
                **extra_args,
            )

        logger.debug(f"Stored artifact in S3 at {key}")
        return path

    async def retrieve(self, path: str) -> Optional[Artifact]:
        """Retrieve content from S3."""
        client = await self._get_client()
        key = self._get_key(path)

        try:
            async with client as s3:
                response = await s3.get_object(
                    Bucket=self.bucket,
                    Key=key,
                )
                body = await response["Body"].read()
                try:
                    content = body.decode("utf-8")
                except UnicodeDecodeError:
                    content = body

                metadata = response.get("Metadata", {})

                return Artifact(
                    path=path,
                    content=content,
                    content_type=response.get("ContentType", "text/plain"),
                    size_bytes=response.get("ContentLength", len(body)),
                    created_at=response.get("LastModified", datetime.now(UTC)),
                    metadata=metadata,
                )
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                return None
            raise

    async def delete(self, path: str) -> bool:
        """Delete content from S3."""
        client = await self._get_client()
        key = self._get_key(path)

        try:
            async with client as s3:
                await s3.delete_object(
                    Bucket=self.bucket,
                    Key=key,
                )
            logger.debug(f"Deleted artifact from S3 at {key}")
            return True
        except Exception:
            return False

    async def exists(self, path: str) -> bool:
        """Check if content exists in S3."""
        client = await self._get_client()
        key = self._get_key(path)

        try:
            async with client as s3:
                await s3.head_object(
                    Bucket=self.bucket,
                    Key=key,
                )
            return True
        except Exception:
            return False

    async def list_directory(self, prefix: str) -> List[str]:
        """List all paths under prefix in S3."""
        client = await self._get_client()
        full_prefix = self._get_key(prefix)

        paths = []
        try:
            async with client as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(
                    Bucket=self.bucket,
                    Prefix=full_prefix,
                ):
                    for obj in page.get("Contents", []):
                        key = obj["Key"]
                        # Remove the base prefix to get relative path
                        rel_path = key[len(self.prefix) + 1 :]
                        paths.append(rel_path)
        except Exception:
            pass

        return sorted(paths)

    # =========================================================================
    # Binary content methods (native S3 support)
    # =========================================================================

    async def store_binary(
        self,
        path: str,
        content: bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store binary content in S3 natively."""
        client = await self._get_client()
        key = self._get_key(path)

        extra_args = {
            "ContentType": content_type,
        }

        if metadata:
            # S3 metadata must be strings
            extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}

        async with client as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                **extra_args,
            )

        logger.debug(f"Stored binary artifact in S3 at {key}")
        return path

    async def retrieve_binary(self, path: str) -> Optional[tuple[bytes, Dict[str, Any]]]:
        """Retrieve binary content from S3 natively."""
        client = await self._get_client()
        key = self._get_key(path)

        try:
            async with client as s3:
                response = await s3.get_object(
                    Bucket=self.bucket,
                    Key=key,
                )
                body = await response["Body"].read()
                metadata = response.get("Metadata", {})
                return (body, metadata)
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                return None
            raise

    # =========================================================================
    # Pre-signed URL support
    # =========================================================================

    async def generate_presigned_url(
        self,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """Generate a pre-signed URL for direct S3 access.

        Args:
            path: Relative path to the object.
            expires_in: URL expiry time in seconds (default 1 hour).

        Returns:
            Pre-signed URL string.
        """
        client = await self._get_client()
        key = self._get_key(path)

        async with client as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        logger.debug(f"Generated pre-signed URL for {key} (expires in {expires_in}s)")
        return url


class AzureBlobBackend(BlobStorageBackend):
    """Azure Blob Storage backend for production.

    Uses azure-storage-blob for async operations.
    """

    def __init__(
        self,
        connection_string: str,
        container_name: str,
        prefix: str = "specs",
    ):
        """Initialize Azure Blob backend.

        Args:
            connection_string: Azure Storage connection string.
            container_name: Container name.
            prefix: Blob prefix for all artifacts.
        """
        self.connection_string = connection_string
        self.container_name = container_name
        self.prefix = prefix
        self._client = None

    async def _get_client(self):
        """Get or create Azure Blob client."""
        if self._client is None:
            try:
                self._client = BlobServiceClient.from_connection_string(self.connection_string)
            except ImportError:
                raise RuntimeError("azure-storage-blob is required for Azure storage backend")
        return self._client

    def _get_blob_name(self, path: str) -> str:
        """Get full blob name from relative path."""
        return f"{self.prefix}/{path}"

    async def store(
        self,
        path: str,
        content: str | bytes,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store content in Azure Blob."""
        client = await self._get_client()
        blob_name = self._get_blob_name(path)

        data: bytes = content.encode("utf-8") if isinstance(content, str) else content

        async with client:
            container = client.get_container_client(self.container_name)
            await container.upload_blob(
                name=blob_name,
                data=data,
                overwrite=True,
                metadata=metadata,
            )

        logger.debug(f"Stored artifact in Azure Blob at {blob_name}")
        return path

    async def retrieve(self, path: str) -> Optional[Artifact]:
        """Retrieve content from Azure Blob."""
        client = await self._get_client()
        blob_name = self._get_blob_name(path)

        try:
            async with client:
                container = client.get_container_client(self.container_name)
                blob = await container.download_blob(blob_name)
                content = await blob.readall()
                try:
                    content_str = content.decode("utf-8")
                except UnicodeDecodeError:
                    content_str = content

                props = await blob.get_blob_properties()

                return Artifact(
                    path=path,
                    content=content_str,
                    content_type=props.content_settings.content_type or "text/plain",
                    size_bytes=props.size,
                    created_at=props.creation_time or datetime.now(UTC),
                    metadata=props.metadata or {},
                )
        except Exception as e:
            if "BlobNotFound" in str(e):
                return None
            raise

    async def delete(self, path: str) -> bool:
        """Delete content from Azure Blob."""
        client = await self._get_client()
        blob_name = self._get_blob_name(path)

        try:
            async with client:
                container = client.get_container_client(self.container_name)
                await container.delete_blob(blob_name)
            logger.debug(f"Deleted artifact from Azure Blob at {blob_name}")
            return True
        except Exception:
            return False

    async def exists(self, path: str) -> bool:
        """Check if content exists in Azure Blob."""
        client = await self._get_client()
        blob_name = self._get_blob_name(path)

        try:
            async with client:
                container = client.get_container_client(self.container_name)
                await container.get_blob_client(blob_name).get_blob_properties()
            return True
        except Exception:
            return False

    async def list_directory(self, prefix: str) -> List[str]:
        """List all paths under prefix in Azure Blob."""
        client = await self._get_client()
        full_prefix = self._get_blob_name(prefix)

        paths = []
        try:
            async with client:
                container = client.get_container_client(self.container_name)
                async for blob in container.list_blobs(name_starts_with=full_prefix):
                    rel_path = blob.name[len(self.prefix) + 1 :]
                    paths.append(rel_path)
        except Exception:
            pass

        return sorted(paths)


class BlobStorage:
    """High-level interface for artifact storage.

    Provides convenient methods for storing documents, story cards,
    and dependency visualizations with automatic path management.
    """

    def __init__(self, backend: BlobStorageBackend):
        """Initialize with a storage backend.

        Args:
            backend: The blob storage backend to use.
        """
        self.backend = backend

    @classmethod
    def from_env(cls) -> "BlobStorage":
        """Create BlobStorage from environment configuration.

        Environment variables:
            SPEC_STORAGE_BACKEND: "local", "s3", or "azure" (default: "local")
            SPEC_STORAGE_PATH: Local path for filesystem storage
            S3_BUCKET, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY for S3
            AZURE_STORAGE_CONNECTION_STRING, AZURE_CONTAINER_NAME for Azure
        """
        backend_type = os.getenv("SPEC_STORAGE_BACKEND", "local").lower()

        if backend_type == "local":
            base_path = os.getenv("SPEC_STORAGE_PATH", "./spec_artifacts")
            backend = LocalFilesystemBackend(base_path)

        elif backend_type == "s3":
            bucket = os.getenv("S3_BUCKET")
            if not bucket:
                raise ValueError("S3_BUCKET is required for S3 storage backend")

            backend = S3Backend(
                bucket=bucket,
                prefix=os.getenv("S3_PREFIX", "specs"),
                region=os.getenv("AWS_REGION", "us-east-1"),
                endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            )

        elif backend_type == "azure":
            connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            container_name = os.getenv("AZURE_CONTAINER_NAME")

            if not connection_string or not container_name:
                raise ValueError(
                    "AZURE_STORAGE_CONNECTION_STRING and AZURE_CONTAINER_NAME are required for Azure storage backend"
                )

            backend = AzureBlobBackend(
                connection_string=connection_string,
                container_name=container_name,
                prefix=os.getenv("AZURE_PREFIX", "specs"),
            )

        else:
            raise ValueError(f"Unknown storage backend: {backend_type}")

        logger.info(f"Initialized BlobStorage with {backend_type} backend")
        return cls(backend)

    # =========================================================================
    # Spec Document Operations
    # =========================================================================

    async def store_spec_document(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store the full specification document.

        Args:
            session_id: Session ID.
            content: Markdown content.
            metadata: Optional metadata.

        Returns:
            Storage path.
        """
        path = f"specs/{session_id}/spec.md"
        return await self.backend.store(
            path,
            content,
            "text/markdown",
            metadata={
                **(metadata or {}),
                "session_id": session_id,
                "stored_at": datetime.now(UTC).isoformat(),
            },
        )

    async def get_spec_document(self, session_id: str) -> Optional[Artifact]:
        """Get the full specification document."""
        path = f"specs/{session_id}/spec.md"
        return await self.backend.retrieve(path)

    # =========================================================================
    # Story Card Operations
    # =========================================================================

    async def store_story_card(
        self,
        session_id: str,
        story_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a single story card.

        Args:
            session_id: Session ID.
            story_id: Story identifier (e.g., "story_1_1").
            content: Markdown content.
            metadata: Optional metadata.

        Returns:
            Storage path.
        """
        path = f"specs/{session_id}/stories/{story_id}.md"
        return await self.backend.store(
            path,
            content,
            "text/markdown",
            metadata={
                **(metadata or {}),
                "session_id": session_id,
                "story_id": story_id,
                "stored_at": datetime.now(UTC).isoformat(),
            },
        )

    async def get_story_card(self, session_id: str, story_id: str) -> Optional[Artifact]:
        """Get a single story card."""
        path = f"specs/{session_id}/stories/{story_id}.md"
        return await self.backend.retrieve(path)

    async def list_story_cards(self, session_id: str) -> List[str]:
        """List all story card IDs for a session."""
        paths = await self.backend.list_directory(f"specs/{session_id}/stories/")
        # Extract story IDs from paths
        return [Path(p).stem for p in paths if p.endswith(".md")]

    # =========================================================================
    # Dependency Graph Operations
    # =========================================================================

    async def store_dependency_graph(
        self,
        session_id: str,
        content: str,
        format: str = "mermaid",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store the dependency visualization.

        Args:
            session_id: Session ID.
            content: Graph content (Mermaid or other format).
            format: Graph format ("mermaid" or "dot").
            metadata: Optional metadata.

        Returns:
            Storage path.
        """
        ext = "mmd" if format == "mermaid" else "dot"
        content_type = "text/vnd.mermaid" if format == "mermaid" else "text/vnd.graphviz"
        path = f"specs/{session_id}/diagrams/dependencies.{ext}"
        return await self.backend.store(
            path,
            content,
            content_type,
            metadata={
                **(metadata or {}),
                "session_id": session_id,
                "format": format,
                "stored_at": datetime.now(UTC).isoformat(),
            },
        )

    async def get_dependency_graph(self, session_id: str) -> Optional[Artifact]:
        """Get the dependency visualization."""
        # Try mermaid first, then dot
        for ext in ["mmd", "dot"]:
            path = f"specs/{session_id}/diagrams/dependencies.{ext}"
            artifact = await self.backend.retrieve(path)
            if artifact:
                return artifact
        return None

    # =========================================================================
    # Session-Level Operations
    # =========================================================================

    async def delete_session_artifacts(self, session_id: str) -> int:
        """Delete all artifacts for a session.

        Args:
            session_id: Session ID.

        Returns:
            Number of artifacts deleted.
        """
        prefix = f"specs/{session_id}/"
        paths = await self.backend.list_directory(prefix)

        count = 0
        for path in paths:
            if await self.backend.delete(path):
                count += 1

        logger.info(f"Deleted {count} artifacts for session {session_id}")
        return count

    async def session_artifacts_exist(self, session_id: str) -> bool:
        """Check if any artifacts exist for a session."""
        prefix = f"specs/{session_id}/"
        paths = await self.backend.list_directory(prefix)
        return len(paths) > 0

    async def get_session_artifacts(self, session_id: str) -> Dict[str, List[str]]:
        """Get a summary of all artifacts for a session.

        Returns:
            Dictionary with categories: "spec", "stories", "diagrams"
        """
        prefix = f"specs/{session_id}/"
        paths = await self.backend.list_directory(prefix)

        result = {
            "spec": [],
            "stories": [],
            "diagrams": [],
        }

        for path in paths:
            if "/spec.md" in path:
                result["spec"].append(path)
            elif "/stories/" in path:
                result["stories"].append(path)
            elif "/diagrams/" in path:
                result["diagrams"].append(path)

        return result
