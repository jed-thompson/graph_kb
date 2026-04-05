"""Async MetadataService — drop-in replacement for the SQLite MetadataStore.

This module provides:
- ``AsyncMetadataService``: Pure async interface backed by PostgreSQL repositories.
- ``SyncMetadataService``: Synchronous wrapper for callers that cannot use async
  (e.g. the legacy IndexerService running in thread-pool workers).

Both expose the **same method names** as the old ``MetadataStore`` so that
call-sites only need an import change, not a full rewrite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graph_kb_api.database.repositories import (
    DocumentRepository,
    EmbeddingProgressRepository,
    FailedEmbeddingChunksRepository,
    FileIndexRepository,
    IndexingProgressRepository,
    PendingChunksRepository,
    RepositoryRepository,
    UserPreferencesRepository,
)
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

if TYPE_CHECKING:
    from graph_kb_api.graph_kb.models.base import (
        DocumentMetadata,
        FileIndexStatus,
        RepoMetadata,
    )
    from graph_kb_api.graph_kb.models.enums import DocumentStatus, RepoStatus
    from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

logger = EnhancedLogger(__name__)


# =========================================================================
# ORM → Domain model converters
# =========================================================================


def _orm_repo_to_domain(orm_obj) -> "RepoMetadata":
    """Convert an ORM Repository to the domain RepoMetadata dataclass."""
    from graph_kb_api.graph_kb.models.base import RepoMetadata
    from graph_kb_api.graph_kb.models.enums import RepoStatus

    return RepoMetadata(
        repo_id=orm_obj.repo_id,
        git_url=orm_obj.git_url,
        default_branch=orm_obj.default_branch,
        local_path=orm_obj.local_path,
        last_indexed_commit=orm_obj.last_indexed_commit,
        last_indexed_at=orm_obj.last_indexed_at,
        status=RepoStatus(orm_obj.status),
        error_message=orm_obj.error_message,
    )


def _orm_doc_to_domain(orm_obj) -> "DocumentMetadata":
    from graph_kb_api.graph_kb.models.base import DocumentMetadata
    from graph_kb_api.graph_kb.models.enums import DocumentStatus

    return DocumentMetadata(
        doc_id=orm_obj.doc_id,
        original_name=orm_obj.original_name,
        file_path=orm_obj.file_path,
        parent_name=orm_obj.parent_name,
        category=orm_obj.category,
        collection_name=orm_obj.collection_name,
        file_hash=orm_obj.file_hash,
        chunk_count=orm_obj.chunk_count,
        status=DocumentStatus(orm_obj.status),
        error_message=orm_obj.error_message,
    )


def _orm_file_to_domain(orm_obj) -> "FileIndexStatus":
    from graph_kb_api.graph_kb.models.base import FileIndexStatus
    from graph_kb_api.graph_kb.models.enums import FileStatus

    return FileIndexStatus(
        repo_id=orm_obj.repo_id,
        file_path=orm_obj.file_path,
        file_hash=orm_obj.file_hash,
        status=FileStatus(orm_obj.status),
        chunk_count=orm_obj.chunk_count or 0,
        symbol_count=orm_obj.symbol_count or 0,
        error_message=orm_obj.error_message,
        indexed_at=orm_obj.indexed_at,
    )


# =========================================================================
# Async Metadata Service
# =========================================================================


class AsyncMetadataService:
    """Pure-async metadata service backed by PostgreSQL repositories.

    Each public method opens its own session, executes, commits, and closes.
    This keeps the service stateless and safe for concurrent use.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    # -- helpers ----------------------------------------------------------

    async def _session(self) -> AsyncSession:
        return self._session_factory()

    # =====================================================================
    # Repository methods
    # =====================================================================

    async def create_repo(self, repo: "RepoMetadata") -> None:
        from graph_kb_api.graph_kb.models.enums import RepoStatus

        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            await repo_repo.create(
                repo_id=repo.repo_id,
                git_url=repo.git_url,
                default_branch=repo.default_branch,
                local_path=repo.local_path,
                status=repo.status
                if isinstance(repo.status, RepoStatus)
                else RepoStatus(repo.status),
            )
            await session.commit()

    async def get_repo(self, repo_id: str) -> Optional["RepoMetadata"]:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            orm_obj = await repo_repo.get(repo_id)
            return _orm_repo_to_domain(orm_obj) if orm_obj else None

    # Alias used by repos router
    get_repository = get_repo

    async def update_status(
        self,
        repo_id: str,
        status: "RepoStatus",
        error_message: Optional[str] = None,
    ) -> None:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            await repo_repo.update_status(repo_id, status, error_message)
            await session.commit()

    async def update_indexed_commit(self, repo_id: str, commit_sha: str) -> None:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            await repo_repo.update_indexed_commit(repo_id, commit_sha)
            await session.commit()

    async def delete_repo(self, repo_id: str) -> bool:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            result = await repo_repo.delete(repo_id)
            await session.commit()
            return result

    # Alias used by repos router
    delete_repository = delete_repo

    async def list_repos(
        self,
        status: Optional["RepoStatus"] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List["RepoMetadata"]:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            orm_list = await repo_repo.list(status=status, limit=limit, offset=offset)
            return [_orm_repo_to_domain(r) for r in orm_list]

    async def count_repos(self, status: Optional["RepoStatus"] = None) -> int:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            return await repo_repo.count(status=status)

    async def repo_exists(self, repo_id: str) -> bool:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            return await repo_repo.exists(repo_id)

    async def update_indexing_phase(self, repo_id: str, phase: str) -> None:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            await repo_repo.update_indexing_phase(repo_id, phase)
            await session.commit()

    async def get_indexing_phase(self, repo_id: str) -> Optional[str]:
        async with self._session_factory() as session:
            repo_repo = RepositoryRepository(session)
            return await repo_repo.get_indexing_phase(repo_id)

    # =====================================================================
    # Document methods
    # =====================================================================

    async def create_document(self, doc: "DocumentMetadata") -> None:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            await doc_repo.create(
                doc_id=doc.doc_id,
                original_name=doc.original_name,
                file_path=doc.file_path,
                parent_name=doc.parent_name,
                category=doc.category,
                collection_name=doc.collection_name,
                file_hash=doc.file_hash,
            )
            await session.commit()

    async def get_document(self, doc_id: str) -> Optional["DocumentMetadata"]:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            orm_obj = await doc_repo.get(doc_id)
            return _orm_doc_to_domain(orm_obj) if orm_obj else None

    async def update_document_status(
        self,
        doc_id: str,
        status: "DocumentStatus",
        error_message: Optional[str] = None,
        chunk_count: Optional[int] = None,
    ) -> None:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            await doc_repo.update_status(doc_id, status, error_message, chunk_count)
            await session.commit()

    async def list_documents(
        self,
        status: Optional["DocumentStatus"] = None,
        category: Optional[str] = None,
        collection_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        parent_name: Optional[str] = None,
    ) -> List["DocumentMetadata"]:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            orm_list = await doc_repo.list(
                parent_name=parent_name,
                status=status,
                category=category,
                collection_name=collection_name,
                limit=limit,
                offset=offset,
            )
            return [_orm_doc_to_domain(d) for d in orm_list]

    async def delete_document(self, doc_id: str) -> bool:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            result = await doc_repo.delete(doc_id)
            await session.commit()
            return result

    async def document_exists(self, doc_id: str) -> bool:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            return await doc_repo.exists(doc_id)

    async def count_documents(
        self,
        status: Optional["DocumentStatus"] = None,
        category: Optional[str] = None,
    ) -> int:
        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            return await doc_repo.count(status=status, category=category)

    # =====================================================================
    # File index methods
    # =====================================================================

    async def upsert_file_status(self, file_status: "FileIndexStatus") -> None:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            await fi_repo.upsert(
                repo_id=file_status.repo_id,
                file_path=file_status.file_path,
                file_hash=file_status.file_hash,
                status=file_status.status,
                chunk_count=file_status.chunk_count,
                symbol_count=file_status.symbol_count,
                error_message=file_status.error_message,
                indexed_at=file_status.indexed_at,
            )
            await session.commit()

    async def get_file_status(
        self, repo_id: str, file_path: str
    ) -> Optional["FileIndexStatus"]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            orm_obj = await fi_repo.get(repo_id, file_path)
            return _orm_file_to_domain(orm_obj) if orm_obj else None

    async def get_processed_files(self, repo_id: str) -> Set[str]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            return await fi_repo.get_processed_files(repo_id)

    async def get_file_status_debug(self, repo_id: str) -> Dict[str, Any]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            return await fi_repo.get_file_status_debug(repo_id)

    async def get_failed_files(self, repo_id: str) -> List["FileIndexStatus"]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            orm_list = await fi_repo.get_failed_files(repo_id)
            return [_orm_file_to_domain(f) for f in orm_list]

    async def get_remaining_files(
        self, repo_id: str, all_files: List[str]
    ) -> List[str]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            return await fi_repo.get_remaining_files(repo_id, all_files)

    async def mark_file_completed(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        chunk_count: int = 0,
        symbol_count: int = 0,
    ) -> None:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            await fi_repo.mark_completed(
                repo_id, file_path, file_hash, chunk_count, symbol_count
            )
            await session.commit()

    async def mark_file_failed(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        error_message: str,
    ) -> None:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            await fi_repo.mark_failed(repo_id, file_path, file_hash, error_message)
            await session.commit()

    async def get_checkpoint_progress(self, repo_id: str) -> Dict[str, int]:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            return await fi_repo.get_checkpoint_progress(repo_id)

    async def clear_file_index(self, repo_id: str) -> None:
        async with self._session_factory() as session:
            fi_repo = FileIndexRepository(session)
            await fi_repo.clear(repo_id)
            await session.commit()

    # =====================================================================
    # Pending chunks methods
    # =====================================================================

    async def save_pending_chunks(
        self,
        repo_id: str,
        chunks_with_file: List[tuple],
        symbol_chunk_links: List[tuple],
    ) -> int:
        """Save pending chunks. Accepts the same (Chunk, file_path) tuples
        as the old SQLite MetadataStore."""
        chunk_symbols: Dict[str, List[str]] = {}
        for symbol_id, chunk_id in symbol_chunk_links:
            chunk_symbols.setdefault(chunk_id, []).append(symbol_id)

        dicts: List[Dict[str, Any]] = []
        for chunk, file_path in chunks_with_file:
            symbol_ids = chunk_symbols.get(chunk.chunk_id, [])
            metadata = {
                "file_path": file_path,
                "repo_id": repo_id,
                "symbols_defined": getattr(chunk, "symbols_defined", []),
                "symbols_referenced": getattr(chunk, "symbols_referenced", []),
                "commit_sha": getattr(chunk, "commit_sha", ""),
            }
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)

            dicts.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "file_path": file_path,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": (
                        chunk.chunk_type.value
                        if hasattr(chunk.chunk_type, "value")
                        else str(chunk.chunk_type)
                    ),
                    "language": (
                        chunk.language.value
                        if hasattr(chunk.language, "value")
                        else str(chunk.language)
                    ),
                    "metadata": metadata,
                    "symbol_ids": symbol_ids,
                }
            )

        async with self._session_factory() as session:
            pc_repo = PendingChunksRepository(session)
            count = await pc_repo.save(repo_id, dicts)
            await session.commit()
            return count

    async def get_pending_chunks(self, repo_id: str) -> tuple:
        """Return (chunks_with_file, symbol_chunk_links) matching old API."""
        from graph_kb_api.graph_kb.models.base import Chunk
        from graph_kb_api.graph_kb.models.enums import Language

        async with self._session_factory() as session:
            pc_repo = PendingChunksRepository(session)
            raw_list = await pc_repo.get(repo_id)

        chunks_with_file = []
        symbol_chunk_links = []

        for row in raw_list:
            try:
                language = Language(row.get("language", "unknown"))
            except (ValueError, KeyError):
                language = Language.UNKNOWN

            metadata = row.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            chunk = Chunk(
                chunk_id=row["chunk_id"],
                repo_id=repo_id,
                file_path=row["file_path"],
                language=language,
                start_line=row.get("start_line"),
                end_line=row.get("end_line"),
                content=row.get("content", ""),
                symbols_defined=metadata.get("symbols_defined", []),
                symbols_referenced=metadata.get("symbols_referenced", []),
                commit_sha=metadata.get("commit_sha", ""),
                created_at=datetime.now(UTC),
                chunk_type=row.get("chunk_type") or "code",
            )
            chunks_with_file.append((chunk, row["file_path"]))

            for sid in row.get("symbol_ids", []):
                symbol_chunk_links.append((sid, row["chunk_id"]))

        return chunks_with_file, symbol_chunk_links

    async def get_pending_chunks_count(self, repo_id: str) -> int:
        async with self._session_factory() as session:
            pc_repo = PendingChunksRepository(session)
            return await pc_repo.count(repo_id)

    async def clear_pending_chunks(self, repo_id: str) -> int:
        async with self._session_factory() as session:
            pc_repo = PendingChunksRepository(session)
            count = await pc_repo.clear(repo_id)
            await session.commit()
            return count

    async def has_pending_chunks(self, repo_id: str) -> bool:
        async with self._session_factory() as session:
            pc_repo = PendingChunksRepository(session)
            return await pc_repo.has_pending(repo_id)

    # =====================================================================
    # Embedding progress methods
    # =====================================================================

    async def init_embedding_progress(self, repo_id: str, total_chunks: int) -> None:
        async with self._session_factory() as session:
            ep_repo = EmbeddingProgressRepository(session)
            await ep_repo.init(repo_id, total_chunks)
            await session.commit()

    async def update_embedding_progress(
        self,
        repo_id: str,
        embedded_chunks: int,
        failed_chunks: int,
        current_chunk_idx: int,
        skipped_chunks: int = 0,
        status: str = "in_progress",
        error_message: Optional[str] = None,
    ) -> None:
        async with self._session_factory() as session:
            ep_repo = EmbeddingProgressRepository(session)
            await ep_repo.update(
                repo_id=repo_id,
                embedded_chunks=embedded_chunks,
                failed_chunks=failed_chunks,
                current_chunk_idx=current_chunk_idx,
                skipped_chunks=skipped_chunks,
                status=status,
                error_message=error_message,
            )
            await session.commit()

    async def get_embedding_progress(self, repo_id: str) -> Optional[Dict[str, Any]]:
        async with self._session_factory() as session:
            ep_repo = EmbeddingProgressRepository(session)
            return await ep_repo.get(repo_id)

    async def clear_embedding_progress(self, repo_id: str) -> None:
        async with self._session_factory() as session:
            ep_repo = EmbeddingProgressRepository(session)
            await ep_repo.clear(repo_id)
            await session.commit()

    # =====================================================================
    # Failed embedding chunks methods
    # =====================================================================

    async def save_failed_embedding_chunks(
        self,
        repo_id: str,
        failed_chunks: List[tuple],
        errors: Dict[int, str],
    ) -> int:
        """Save failed chunks. Accepts (Chunk, file_node_id) tuples."""
        dicts: List[Dict[str, Any]] = []
        for chunk, file_node_id in failed_chunks:
            dicts.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "file_path": file_node_id,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": (
                        chunk.chunk_type.value
                        if hasattr(chunk.chunk_type, "value")
                        else str(chunk.chunk_type)
                    ),
                    "language": (
                        chunk.language.value
                        if hasattr(chunk.language, "value")
                        else str(chunk.language)
                    ),
                }
            )

        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            count = await fec_repo.save(repo_id, dicts, errors)
            await session.commit()
            return count

    async def get_failed_embedding_chunks(
        self, repo_id: str, max_retries: int = 3
    ) -> tuple:
        """Return (chunks_with_file, symbol_chunk_links) matching old API."""
        from graph_kb_api.graph_kb.models.base import Chunk
        from graph_kb_api.graph_kb.models.enums import Language

        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            raw_list = await fec_repo.get(repo_id, max_retries)

        chunks_with_file = []
        symbol_chunk_links: List[tuple] = []

        for row in raw_list:
            try:
                language = Language(row.get("language", "unknown"))
            except (ValueError, KeyError):
                language = Language.UNKNOWN

            chunk = Chunk(
                chunk_id=row["chunk_id"],
                repo_id=repo_id,
                file_path=row["file_path"],
                language=language,
                start_line=row.get("start_line"),
                end_line=row.get("end_line"),
                content=row.get("content", ""),
                symbols_defined=[],
                symbols_referenced=[],
                commit_sha="",
                created_at=datetime.now(UTC),
                chunk_type=row.get("chunk_type") or "code",
            )
            chunks_with_file.append((chunk, row["file_path"]))

        return chunks_with_file, symbol_chunk_links

    async def get_failed_embedding_chunks_count(self, repo_id: str) -> int:
        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            return await fec_repo.count(repo_id)

    async def clear_failed_embedding_chunks(
        self, repo_id: str, chunk_ids: Optional[List[str]] = None
    ) -> int:
        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            count = await fec_repo.clear(repo_id, chunk_ids)
            await session.commit()
            return count

    async def has_failed_embedding_chunks(self, repo_id: str) -> bool:
        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            return await fec_repo.has_failed(repo_id)

    async def get_failed_embedding_stats(self, repo_id: str) -> Dict[str, Any]:
        async with self._session_factory() as session:
            fec_repo = FailedEmbeddingChunksRepository(session)
            return await fec_repo.get_stats(repo_id)

    # =====================================================================
    # Indexing progress methods
    # =====================================================================

    async def save_indexing_progress(
        self,
        repo_id: str,
        phase: str,
        total_files: int = 0,
        processed_files: int = 0,
        current_file: Optional[str] = None,
        total_chunks: int = 0,
        total_symbols: int = 0,
        total_relationships: int = 0,
        embedded_chunks: int = 0,
        total_chunks_to_embed: int = 0,
        message: str = "",
    ) -> None:
        async with self._session_factory() as session:
            ip_repo = IndexingProgressRepository(session)
            await ip_repo.save(
                repo_id=repo_id,
                phase=phase,
                total_files=total_files,
                processed_files=processed_files,
                current_file=current_file,
                total_chunks=total_chunks,
                total_symbols=total_symbols,
                total_relationships=total_relationships,
                embedded_chunks=embedded_chunks,
                total_chunks_to_embed=total_chunks_to_embed,
                message=message,
            )
            await session.commit()

    async def get_indexing_progress(self, repo_id: str) -> Optional[Dict[str, Any]]:
        async with self._session_factory() as session:
            ip_repo = IndexingProgressRepository(session)
            return await ip_repo.get(repo_id)

    async def delete_indexing_progress(self, repo_id: str) -> None:
        async with self._session_factory() as session:
            ip_repo = IndexingProgressRepository(session)
            await ip_repo.delete(repo_id)
            await session.commit()

    async def is_repo_actively_indexing(self, repo_id: str) -> bool:
        async with self._session_factory() as session:
            ip_repo = IndexingProgressRepository(session)
            return await ip_repo.is_active(repo_id)

    # =====================================================================
    # User preferences methods
    # =====================================================================

    async def save_user_preferences(
        self, user_id: str, settings: "RetrievalConfig"
    ) -> None:
        async with self._session_factory() as session:
            up_repo = UserPreferencesRepository(session)
            settings_json = settings.to_json()
            data = (
                json.loads(settings_json)
                if isinstance(settings_json, str)
                else settings_json
            )
            await up_repo.save(user_id, data)
            await session.commit()

    async def load_user_preferences(self, user_id: str) -> Optional["RetrievalConfig"]:
        from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

        async with self._session_factory() as session:
            up_repo = UserPreferencesRepository(session)
            data = await up_repo.load(user_id)
            if data is None:
                return None
            try:
                json_str = json.dumps(data) if isinstance(data, dict) else data
                return RetrievalConfig.from_json(json_str)
            except Exception as e:
                logger.warning(f"Failed to parse preferences for {user_id}: {e}")
                return None

    async def delete_user_preferences(self, user_id: str) -> bool:
        async with self._session_factory() as session:
            up_repo = UserPreferencesRepository(session)
            result = await up_repo.delete(user_id)
            await session.commit()
            return result

    async def load_raw_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load raw preferences dict directly from the repository.

        Unlike ``load_user_preferences`` which deserialises into a
        ``RetrievalConfig``, this returns the raw JSON dict — useful for
        storing arbitrary key/value settings (e.g. model, temperature).
        """
        async with self._session_factory() as session:
            up_repo = UserPreferencesRepository(session)
            return await up_repo.load(user_id)

    async def save_raw_preferences(self, user_id: str, data: Dict[str, Any]) -> None:
        """Save a raw dict directly into the user_preferences table."""
        async with self._session_factory() as session:
            up_repo = UserPreferencesRepository(session)
            await up_repo.save(user_id, data)
            await session.commit()

    # =====================================================================
    # Lifecycle
    # =====================================================================

    async def close(self) -> None:
        """No-op — engine lifecycle is managed by database.base."""
        pass


# =========================================================================
# Sync wrapper for legacy callers (IndexerService, LangChain tools, etc.)
# =========================================================================


class SyncMetadataService:
    """Synchronous facade over ``AsyncMetadataService``.

    Uses a dedicated event loop running in a background thread so that
    sync callers (e.g. ``IndexerService`` running inside
    ``ThreadPoolExecutor``) can call metadata methods without blocking
    the main asyncio loop.

    IMPORTANT: Creates its own async engine + session factory for the
    background loop.  asyncpg connections are bound to the event loop
    they were created on, so sharing the main-loop engine would cause
    "Future attached to a different loop" errors.
    """

    def __init__(self, async_service: AsyncMetadataService):
        self._async = async_service
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Any] = None
        self._ensure_loop()
        # Build a private engine + session factory on the background loop
        # so asyncpg connections are bound to the correct loop.
        self._init_private_session_factory()

    # -- internal ---------------------------------------------------------

    def _ensure_loop(self) -> None:
        """Create a background event loop if one doesn't exist."""
        import threading

        if self._loop is not None and self._loop.is_running():
            return

        self._loop = asyncio.new_event_loop()

        def _run(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._thread = threading.Thread(
            target=_run, args=(self._loop,), daemon=True, name="metadata-sync-loop"
        )
        self._thread.start()

    def _init_private_session_factory(self) -> None:
        """Create a dedicated engine + session factory on the background loop.

        This ensures all asyncpg connections are created on (and bound to)
        the background event loop, avoiding cross-loop Future errors.
        """
        from sqlalchemy.ext.asyncio import (
            AsyncSession as _AS,
        )
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker as _asm,
        )
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
        )

        async def _create():
            from graph_kb_api.database.base import get_database_url, get_pool_config

            url = get_database_url()
            pool_cfg = get_pool_config()
            engine = create_async_engine(
                url,
                echo=False,
                pool_size=pool_cfg["pool_size"],
                max_overflow=pool_cfg["max_overflow"],
                pool_pre_ping=True,
            )
            factory = _asm(
                bind=engine,
                class_=_AS,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            return engine, factory

        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(_create(), self._loop)
        self._private_engine, private_factory = future.result(timeout=30)
        # Patch the wrapped async service to use the private factory
        self._async = AsyncMetadataService(private_factory)

    def _run(self, coro):
        """Submit a coroutine to the background loop and wait for the result."""
        if self._loop is None or not self._loop.is_running():
            self._ensure_loop()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    # -- Repository -------------------------------------------------------

    def create_repo(self, repo) -> None:
        self._run(self._async.create_repo(repo))

    def get_repo(self, repo_id: str):
        return self._run(self._async.get_repo(repo_id))

    get_repository = get_repo

    def update_status(self, repo_id, status, error_message=None):
        self._run(self._async.update_status(repo_id, status, error_message))

    def update_indexed_commit(self, repo_id, commit_sha):
        self._run(self._async.update_indexed_commit(repo_id, commit_sha))

    def delete_repo(self, repo_id):
        return self._run(self._async.delete_repo(repo_id))

    delete_repository = delete_repo

    def list_repos(self, status=None, limit=100, offset=0):
        return self._run(self._async.list_repos(status, limit, offset))

    def count_repos(self, status=None):
        return self._run(self._async.count_repos(status))

    def repo_exists(self, repo_id):
        return self._run(self._async.repo_exists(repo_id))

    def update_indexing_phase(self, repo_id, phase):
        self._run(self._async.update_indexing_phase(repo_id, phase))

    def get_indexing_phase(self, repo_id):
        return self._run(self._async.get_indexing_phase(repo_id))

    # -- Document ---------------------------------------------------------

    def create_document(self, doc):
        self._run(self._async.create_document(doc))

    def get_document(self, doc_id):
        return self._run(self._async.get_document(doc_id))

    def update_document_status(
        self, doc_id, status, error_message=None, chunk_count=None
    ):
        self._run(
            self._async.update_document_status(
                doc_id, status, error_message, chunk_count
            )
        )

    def list_documents(
        self,
        status=None,
        category=None,
        collection_name=None,
        limit=100,
        offset=0,
        parent_name=None,
    ):
        return self._run(
            self._async.list_documents(
                status=status,
                category=category,
                collection_name=collection_name,
                limit=limit,
                offset=offset,
                parent_name=parent_name,
            )
        )

    def delete_document(self, doc_id):
        return self._run(self._async.delete_document(doc_id))

    def document_exists(self, doc_id):
        return self._run(self._async.document_exists(doc_id))

    def count_documents(self, status=None, category=None):
        return self._run(self._async.count_documents(status, category))

    # -- File index -------------------------------------------------------

    def upsert_file_status(self, file_status):
        self._run(self._async.upsert_file_status(file_status))

    def get_file_status(self, repo_id, file_path):
        return self._run(self._async.get_file_status(repo_id, file_path))

    def get_processed_files(self, repo_id):
        return self._run(self._async.get_processed_files(repo_id))

    def get_file_status_debug(self, repo_id):
        return self._run(self._async.get_file_status_debug(repo_id))

    def get_failed_files(self, repo_id):
        return self._run(self._async.get_failed_files(repo_id))

    def get_remaining_files(self, repo_id, all_files):
        return self._run(self._async.get_remaining_files(repo_id, all_files))

    def mark_file_completed(
        self, repo_id, file_path, file_hash, chunk_count=0, symbol_count=0
    ):
        self._run(
            self._async.mark_file_completed(
                repo_id, file_path, file_hash, chunk_count, symbol_count
            )
        )

    def mark_file_failed(self, repo_id, file_path, file_hash, error_message=""):
        self._run(
            self._async.mark_file_failed(repo_id, file_path, file_hash, error_message)
        )

    def get_checkpoint_progress(self, repo_id):
        return self._run(self._async.get_checkpoint_progress(repo_id))

    def clear_file_index(self, repo_id):
        self._run(self._async.clear_file_index(repo_id))

    # -- Pending chunks ---------------------------------------------------

    def save_pending_chunks(self, repo_id, chunks_with_file, symbol_chunk_links):
        return self._run(
            self._async.save_pending_chunks(
                repo_id, chunks_with_file, symbol_chunk_links
            )
        )

    def get_pending_chunks(self, repo_id):
        return self._run(self._async.get_pending_chunks(repo_id))

    def get_pending_chunks_count(self, repo_id):
        return self._run(self._async.get_pending_chunks_count(repo_id))

    def clear_pending_chunks(self, repo_id):
        return self._run(self._async.clear_pending_chunks(repo_id))

    def has_pending_chunks(self, repo_id):
        return self._run(self._async.has_pending_chunks(repo_id))

    # -- Embedding progress -----------------------------------------------

    def init_embedding_progress(self, repo_id, total_chunks):
        self._run(self._async.init_embedding_progress(repo_id, total_chunks))

    def update_embedding_progress(
        self,
        repo_id,
        embedded_chunks,
        failed_chunks,
        current_chunk_idx,
        skipped_chunks=0,
        status="in_progress",
        error_message=None,
    ):
        self._run(
            self._async.update_embedding_progress(
                repo_id,
                embedded_chunks,
                failed_chunks,
                current_chunk_idx,
                skipped_chunks,
                status,
                error_message,
            )
        )

    def get_embedding_progress(self, repo_id):
        return self._run(self._async.get_embedding_progress(repo_id))

    def clear_embedding_progress(self, repo_id):
        self._run(self._async.clear_embedding_progress(repo_id))

    # -- Failed embedding chunks ------------------------------------------

    def save_failed_embedding_chunks(self, repo_id, failed_chunks, errors):
        return self._run(
            self._async.save_failed_embedding_chunks(repo_id, failed_chunks, errors)
        )

    def get_failed_embedding_chunks(self, repo_id, max_retries=3):
        return self._run(self._async.get_failed_embedding_chunks(repo_id, max_retries))

    def get_failed_embedding_chunks_count(self, repo_id):
        return self._run(self._async.get_failed_embedding_chunks_count(repo_id))

    def clear_failed_embedding_chunks(self, repo_id, chunk_ids=None):
        return self._run(self._async.clear_failed_embedding_chunks(repo_id, chunk_ids))

    def has_failed_embedding_chunks(self, repo_id):
        return self._run(self._async.has_failed_embedding_chunks(repo_id))

    def get_failed_embedding_stats(self, repo_id):
        return self._run(self._async.get_failed_embedding_stats(repo_id))

    # -- Indexing progress ------------------------------------------------

    def save_indexing_progress(
        self,
        repo_id,
        phase,
        total_files=0,
        processed_files=0,
        current_file=None,
        total_chunks=0,
        total_symbols=0,
        total_relationships=0,
        embedded_chunks=0,
        total_chunks_to_embed=0,
        message="",
    ):
        self._run(
            self._async.save_indexing_progress(
                repo_id,
                phase,
                total_files,
                processed_files,
                current_file,
                total_chunks,
                total_symbols,
                total_relationships,
                embedded_chunks,
                total_chunks_to_embed,
                message,
            )
        )

    def get_indexing_progress(self, repo_id):
        return self._run(self._async.get_indexing_progress(repo_id))

    def delete_indexing_progress(self, repo_id):
        self._run(self._async.delete_indexing_progress(repo_id))

    def is_repo_actively_indexing(self, repo_id):
        return self._run(self._async.is_repo_actively_indexing(repo_id))

    # -- User preferences -------------------------------------------------

    def save_user_preferences(self, user_id, settings):
        self._run(self._async.save_user_preferences(user_id, settings))

    def load_user_preferences(self, user_id):
        return self._run(self._async.load_user_preferences(user_id))

    def delete_user_preferences(self, user_id):
        return self._run(self._async.delete_user_preferences(user_id))

    def load_raw_preferences(self, user_id):
        return self._run(self._async.load_raw_preferences(user_id))

    def save_raw_preferences(self, user_id, data):
        self._run(self._async.save_raw_preferences(user_id, data))

    # -- Lifecycle --------------------------------------------------------

    def close(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
