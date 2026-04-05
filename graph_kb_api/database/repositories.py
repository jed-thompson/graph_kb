"""Async repository pattern classes for data access.

This module provides async repository classes for all 8 tables,
implementing the repository pattern for separation of concerns:

- BaseRepository: Common CRUD operations
- RepositoryRepository: Repositories table
- DocumentRepository: Documents table
- FileIndexRepository: FileIndex table
- PendingChunksRepository: PendingChunk table
- FailedEmbeddingChunksRepository: FailedEmbeddingChunk table
- EmbeddingProgressRepository: EmbeddingProgress table
- IndexingProgressRepository: IndexingProgress table
- UserPreferencesRepository: UserPreference table
"""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from graph_kb_api.database.base import DatabaseError
from graph_kb_api.database.models import (
    Document,
    EmbeddingProgress,
    FailedEmbeddingChunk,
    FileIndex,
    IndexingProgress,
    PendingChunk,
    Repository,
    UserPreference,
)
from graph_kb_api.graph_kb.models.enums import DocumentStatus, FileStatus, RepoStatus
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


# =========================================================================
# Base Repository
# =========================================================================


class BaseRepository:
    """Base repository with common CRUD operations.

    This class provides common patterns for:
    - Create operations
    - Read operations (get, list, exists)
    - Update operations
    - Delete operations
    - Count operations
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: Async database session.
        """
        self.session = session

    async def _execute(self, query) -> Any:
        """Execute a query and handle errors.

        Args:
            query: SQLAlchemy query to execute.

        Returns:
            Query result.

        Raises:
            DatabaseError: If query execution fails.
        """
        try:
            result = await self.session.execute(query)
            return result
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise DatabaseError(f"Database query failed: {e}", original=e) from e


# =========================================================================
# Repository Table
# =========================================================================


class RepositoryRepository(BaseRepository):
    """Repository for repositories table operations."""

    async def create(
        self,
        repo_id: str,
        git_url: str,
        default_branch: str,
        local_path: str,
        last_indexed_commit: Optional[str] = None,
        last_indexed_at: Optional[datetime] = None,
        status: RepoStatus = RepoStatus.PENDING,
        error_message: Optional[str] = None,
    ) -> None:
        """Create a new repository record.

        Args:
            repo_id: Unique repository identifier.
            git_url: Git repository URL.
            default_branch: Default branch name.
            local_path: Local filesystem path.
            last_indexed_commit: Last indexed commit SHA.
            last_indexed_at: Timestamp of last indexing.
            status: Repository status.
            error_message: Error message if status is ERROR.

        Raises:
            DatabaseError: If creation fails.
        """
        now = datetime.now(UTC)

        repo = Repository(
            repo_id=repo_id,
            git_url=git_url,
            default_branch=default_branch,
            local_path=local_path,
            last_indexed_commit=last_indexed_commit,
            last_indexed_at=last_indexed_at,
            status=status,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )

        self.session.add(repo)
        await self.session.flush()
        logger.info(f"Created repository: {repo_id}")

    async def get(self, repo_id: str) -> Optional[Repository]:
        """Get a repository by ID.

        Args:
            repo_id: Repository identifier.

        Returns:
            Repository if found, None otherwise.

        Raises:
            DatabaseError: If query fails.
        """
        result = await self._execute(select(Repository).where(Repository.repo_id == repo_id))
        return result.scalar_one_or_none()

    async def update_status(
        self,
        repo_id: str,
        status: RepoStatus,
        error_message: Optional[str] = None,
        validate_transition: bool = True,
    ) -> None:
        """Update repository status.

        Args:
            repo_id: Repository identifier.
            status: New status value.
            error_message: Optional error message for ERROR status.
            validate_transition: Whether to validate status transitions.

        Raises:
            DatabaseError: If update fails.
        """
        # Validate transition if requested
        if validate_transition:
            repo = await self.get(repo_id)
            if not repo:
                raise DatabaseError(f"Repository {repo_id} not found")

            valid_transitions = {
                "pending": {"indexing"},
                "indexing": {
                    "ready",
                    "error",
                    "paused",
                    "indexing",
                },
                "paused": {"indexing", "error"},
                "ready": {"indexing"},
                "error": {"pending", "indexing"},
            }

            # Normalize status values - repo.status is a string, status param may be enum or string
            current_status = repo.status  # Already a string from DB
            valid_next = valid_transitions.get(current_status, set())
            # Handle both enum and string status values
            new_status = status.value if hasattr(status, "value") else str(status)

            if new_status not in valid_next:
                logger.warning(f"Invalid status transition for {repo_id}: {current_status} -> {new_status}")
                raise DatabaseError(
                    f"Invalid status transition from {current_status} to {new_status}. Valid: {list(valid_next)}"
                )

        now = datetime.now(UTC)
        # Ensure status is stored as string
        status_value = status.value if hasattr(status, "value") else str(status)
        await self._execute(
            update(Repository)
            .where(Repository.repo_id == repo_id)
            .values(
                status=status_value,
                error_message=error_message,
                updated_at=now,
            )
        )
        logger.info(f"Updated repository {repo_id} status to {status_value}")

    async def update_indexed_commit(
        self,
        repo_id: str,
        commit_sha: str,
    ) -> None:
        """Update last indexed commit for a repository.

        Args:
            repo_id: Repository identifier.
            commit_sha: Commit SHA that was indexed.

        Raises:
            DatabaseError: If update fails.
        """
        now = datetime.now(UTC)
        await self._execute(
            update(Repository)
            .where(Repository.repo_id == repo_id)
            .values(
                last_indexed_commit=commit_sha,
                last_indexed_at=now,
                updated_at=now,
            )
        )

    async def delete(self, repo_id: str) -> bool:
        """Delete a repository and all dependent records via ORM cascade.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if deleted, False if not found.

        Raises:
            DatabaseError: If delete fails.
        """
        repo = await self.get(repo_id)
        if repo is None:
            return False
        await self.session.delete(repo)
        await self.session.flush()
        logger.info(f"Deleted repository: {repo_id}")
        return True

    async def list(
        self,
        status: Optional[RepoStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Repository]:
        """List repositories with optional filtering and pagination.

        Args:
            status: Optional status filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of Repository objects.

        Raises:
            DatabaseError: If query fails.
        """
        query = select(Repository)

        if status is not None:
            query = query.where(Repository.status == status)

        query = query.order_by(Repository.updated_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._execute(query)
        return list(result.scalars().all())

    async def count(self, status: Optional[RepoStatus] = None) -> int:
        """Count repositories with optional filter.

        Args:
            status: Optional status filter.

        Returns:
            Number of matching repositories.

        Raises:
            DatabaseError: If query fails.
        """
        query = select(func.count()).select_from(Repository)

        if status is not None:
            query = query.where(Repository.status == status)

        result = await self._execute(query)
        return result.scalar() or 0

    async def exists(self, repo_id: str) -> bool:
        """Check if a repository exists.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if exists, False otherwise.

        Raises:
            DatabaseError: If query fails.
        """
        return await self.get(repo_id) is not None

    async def update_indexing_phase(self, repo_id: str, phase: str) -> None:
        """Update indexing phase for a repository.

        Args:
            repo_id: Repository identifier.
            phase: Indexing phase ('indexing', 'embedding', 'completed', 'error').

        Raises:
            DatabaseError: If update fails.
        """
        now = datetime.now(UTC)
        await self._execute(
            update(Repository)
            .where(Repository.repo_id == repo_id)
            .values(
                indexing_phase=phase,
                updated_at=now,
            )
        )

    async def get_indexing_phase(self, repo_id: str) -> Optional[str]:
        """Get current indexing phase for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            The indexing phase string, or None if not found.
        """
        repo = await self.get(repo_id)
        return repo.indexing_phase.value if repo and repo.indexing_phase else None


# =========================================================================
# Document Table
# =========================================================================


class DocumentRepository(BaseRepository):
    """Repository for documents table operations."""

    async def create(
        self,
        doc_id: str,
        original_name: str,
        file_path: Optional[str] = None,
        parent_name: Optional[str] = None,
        category: Optional[str] = None,
        collection_name: Optional[str] = None,
        file_hash: Optional[str] = None,
        chunk_count: int = 0,
        status: DocumentStatus = DocumentStatus.PENDING,
        error_message: Optional[str] = None,
    ) -> None:
        """Create a new document record.

        Args:
            doc_id: Unique document identifier.
            original_name: Original filename.
            file_path: Optional file path.
            parent_name: Optional parent directory name.
            category: Optional document category.
            collection_name: Optional collection name.
            file_hash: Optional file hash.
            chunk_count: Number of chunks.
            status: Document status.
            error_message: Optional error message.

        Raises:
            DatabaseError: If creation fails.
        """
        now = datetime.now(UTC)

        doc = Document(
            doc_id=doc_id,
            original_name=original_name,
            file_path=file_path,
            parent_name=parent_name,
            category=category,
            collection_name=collection_name,
            file_hash=file_hash,
            chunk_count=chunk_count,
            status=status,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )

        self.session.add(doc)
        await self.session.flush()
        logger.info(f"Created document: {doc_id}")

    async def get(self, doc_id: str) -> Optional[Document]:
        """Get a document by ID.

        Args:
            doc_id: Document identifier.

        Returns:
            Document if found, None otherwise.
        """
        result = await self._execute(select(Document).where(Document.doc_id == doc_id))
        return result.scalar_one_or_none()

    async def update_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        chunk_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update document status.

        Args:
            doc_id: Document identifier.
            status: New status value.
            chunk_count: Optional chunk count to update.
            error_message: Optional error message.

        Raises:
            DatabaseError: If update fails.
        """
        doc = await self.get(doc_id)
        if not doc:
            raise DatabaseError(f"Document {doc_id} not found")

        now = datetime.now(UTC)
        values = {
            "status": status,
            "error_message": error_message,
            "updated_at": now,
        }
        if chunk_count is not None:
            values["chunk_count"] = chunk_count

        await self._execute(update(Document).where(Document.doc_id == doc_id).values(**values))

    async def list(
        self,
        parent_name: Optional[str] = None,
        category: Optional[str] = None,
        collection_name: Optional[str] = None,
        status: Optional[DocumentStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Document]:
        """List documents with optional filtering and pagination.

        Args:
            parent_name: Optional parent name filter.
            category: Optional category filter.
            collection_name: Optional collection name filter.
            status: Optional status filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of Document objects.
        """
        query = select(Document)

        conditions = []
        if parent_name is not None:
            conditions.append(Document.parent_name == parent_name)
        if category is not None:
            conditions.append(Document.category == category)
        if collection_name is not None:
            conditions.append(Document.collection_name == collection_name)
        if status is not None:
            conditions.append(Document.status == status)

        for condition in conditions:
            query: Select[tuple[Document]] = query.where(condition)

        query: Select[tuple[Document]] = query.order_by(Document.updated_at.desc())
        query: Select[tuple[Document]] = query.limit(limit).offset(offset)

        result = await self._execute(query)
        return list(result.scalars().all())

    async def delete(self, doc_id: str) -> bool:
        """Delete a document.

        Args:
            doc_id: Document identifier.

        Returns:
            True if deleted, False if not found.
        """
        result = await self._execute(delete(Document).where(Document.doc_id == doc_id))
        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"Deleted document: {doc_id}")
        return deleted

    async def exists(self, doc_id: str) -> bool:
        """Check if a document exists.

        Args:
            doc_id: Document identifier.

        Returns:
            True if exists, False otherwise.
        """
        return await self.get(doc_id) is not None

    async def count(
        self,
        parent_name: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[DocumentStatus] = None,
    ) -> int:
        """Count documents with optional filters.

        Args:
            parent_name: Optional parent name filter.
            category: Optional category filter.
            status: Optional status filter.

        Returns:
            Number of matching documents.
        """
        query = select(func.count()).select_from(Document)

        conditions = []
        if parent_name is not None:
            conditions.append(Document.parent_name == parent_name)
        if category is not None:
            conditions.append(Document.category == category)
        if status is not None:
            conditions.append(Document.status == status)

        for condition in conditions:
            query = query.where(condition)

        result = await self._execute(query)
        return result.scalar() or 0


# =========================================================================
# File Index Table
# =========================================================================


class FileIndexRepository(BaseRepository):
    """Repository for file_index table operations (checkpoint tracking)."""

    async def upsert(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        status: FileStatus = FileStatus.PENDING,
        chunk_count: int = 0,
        symbol_count: int = 0,
        error_message: Optional[str] = None,
        indexed_at: Optional[datetime] = None,
    ) -> None:
        """Create or update file indexing status.

        Args:
            repo_id: Repository identifier.
            file_path: File path within repository.
            file_hash: Hash of file content.
            status: Indexing status.
            chunk_count: Number of chunks created.
            symbol_count: Number of symbols extracted.
            error_message: Optional error message.
            indexed_at: Timestamp of indexing.

        Raises:
            DatabaseError: If upsert fails.
        """
        now = datetime.now(UTC)

        # Check if exists (for update logic)
        existing = await self.get(repo_id, file_path)

        if existing:
            # Update existing record
            await self._execute(
                update(FileIndex)
                .where(FileIndex.repo_id == repo_id, FileIndex.file_path == file_path)
                .values(
                    file_hash=file_hash,
                    status=status,
                    chunk_count=chunk_count,
                    symbol_count=symbol_count,
                    error_message=error_message,
                    indexed_at=indexed_at or now,
                    updated_at=now,
                )
            )
            logger.debug(f"Updated file index: {repo_id}:{file_path}")
        else:
            # Insert new record
            file_idx = FileIndex(
                repo_id=repo_id,
                file_path=file_path,
                file_hash=file_hash,
                status=status,
                chunk_count=chunk_count,
                symbol_count=symbol_count,
                error_message=error_message,
                indexed_at=indexed_at,
            )
            self.session.add(file_idx)
            await self.session.flush()
            logger.debug(f"Created file index: {repo_id}:{file_path}")

    async def get(self, repo_id: str, file_path: str) -> Optional[FileIndex]:
        """Get file indexing status.

        Args:
            repo_id: Repository identifier.
            file_path: File path within repository.

        Returns:
            FileIndex if found, None otherwise.
        """
        result = await self._execute(
            select(FileIndex).where(FileIndex.repo_id == repo_id, FileIndex.file_path == file_path)
        )
        return result.scalar_one_or_none()

    async def get_processed_files(self, repo_id: str) -> Set[str]:
        """Get set of file paths that have been successfully indexed.

        Args:
            repo_id: Repository identifier.

        Returns:
            Set of file paths with COMPLETED status.
        """
        result = await self._execute(
            select(FileIndex.file_path).where(FileIndex.repo_id == repo_id, FileIndex.status == "completed")
        )
        return {row[0] for row in result.all()}

    async def mark_completed(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        chunk_count: int = 0,
        symbol_count: int = 0,
    ) -> None:
        """Mark a file as successfully indexed.

        Args:
            repo_id: Repository identifier.
            file_path: File path.
            file_hash: Hash of file content.
            chunk_count: Number of chunks.
            symbol_count: Number of symbols.
        """
        await self.upsert(
            repo_id=repo_id,
            file_path=file_path,
            file_hash=file_hash,
            status=FileStatus.COMPLETED,
            chunk_count=chunk_count,
            symbol_count=symbol_count,
            indexed_at=datetime.now(UTC),
        )

    async def mark_failed(
        self,
        repo_id: str,
        file_path: str,
        file_hash: str,
        error_message: str,
    ) -> None:
        """Mark a file as failed with error message.

        Args:
            repo_id: Repository identifier.
            file_path: File path.
            file_hash: Hash of file content.
            error_message: Description of error.
        """
        await self.upsert(
            repo_id=repo_id,
            file_path=file_path,
            file_hash=file_hash,
            status=FileStatus.FAILED,
            error_message=error_message,
        )

    async def get_checkpoint_progress(self, repo_id: str) -> Dict[str, Any]:
        """Get checkpoint progress stats.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dictionary with: total, completed, failed, pending,
            processing, skipped, total_chunks, total_symbols.
        """
        result = await self._execute(
            select(
                FileIndex.status,
                func.count(FileIndex.status).label("count"),
            )
            .where(FileIndex.repo_id == repo_id)
            .group_by(FileIndex.status)
        )

        stats = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "pending": 0,
            "processing": 0,
            "skipped": 0,
            "total_chunks": 0,
            "total_symbols": 0,
        }

        for row in result.all():
            status = row[0]
            count = row[1]
            stats["total"] += count

            if status == "completed":
                stats["completed"] = count
            elif status == "failed":
                stats["failed"] = count
            elif status == "pending":
                stats["pending"] = count
            elif status == "processing":
                stats["processing"] = count
            elif status == "skipped":
                stats["skipped"] = count

        # Get total chunks and symbols from completed files
        chunks_result = await self._execute(
            select(
                func.sum(FileIndex.chunk_count).label("total_chunks"),
                func.sum(FileIndex.symbol_count).label("total_symbols"),
            ).where(
                FileIndex.repo_id == repo_id,
                FileIndex.status == "completed",
            )
        )
        row = chunks_result.one_or_none()
        if row:
            stats["total_chunks"] = row.total_chunks or 0
            stats["total_symbols"] = row.total_symbols or 0

        return stats

    async def clear(self, repo_id: str) -> int:
        """Clear all file index entries for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            Number of entries deleted.
        """
        result = await self._execute(delete(FileIndex).where(FileIndex.repo_id == repo_id))
        count = result.rowcount
        logger.info(f"Cleared {count} file index entries for repo {repo_id}")
        return count

    async def get_file_status_debug(self, repo_id: str) -> Dict[str, Any]:
        """Get detailed file status information for debugging.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dictionary with status_counts and sample_files.
        """
        # Status counts
        result = await self._execute(
            select(
                FileIndex.status,
                func.count(FileIndex.status).label("count"),
            )
            .where(FileIndex.repo_id == repo_id)
            .group_by(FileIndex.status)
        )
        status_counts = {row[0]: row[1] for row in result.all()}

        # Sample files (limit 20)
        result = await self._execute(
            select(
                FileIndex.status,
                FileIndex.file_path,
                FileIndex.chunk_count,
                FileIndex.symbol_count,
            )
            .where(FileIndex.repo_id == repo_id)
            .order_by(FileIndex.status, FileIndex.file_path)
            .limit(20)
        )
        sample_files = [
            {
                "status": row[0],
                "file_path": row[1],
                "chunk_count": row[2],
                "symbol_count": row[3],
            }
            for row in result.all()
        ]

        return {"status_counts": status_counts, "sample_files": sample_files}

    async def get_failed_files(self, repo_id: str) -> List[FileIndex]:
        """Get files that failed indexing.

        Args:
            repo_id: Repository identifier.

        Returns:
            List of FileIndex records with FAILED status.
        """
        result = await self._execute(
            select(FileIndex).where(
                FileIndex.repo_id == repo_id,
                FileIndex.status == "failed",
            )
        )
        return list(result.scalars().all())

    async def get_remaining_files(self, repo_id: str, all_files: List[str]) -> List[str]:
        """Get files that still need to be indexed (not completed).

        Args:
            repo_id: Repository identifier.
            all_files: List of all file paths to be indexed.

        Returns:
            List of file paths that need to be indexed.
        """
        completed = await self.get_processed_files(repo_id)
        return [f for f in all_files if f not in completed]


# =========================================================================
# Pending Chunks Table
# =========================================================================


class PendingChunksRepository(BaseRepository):
    """Repository for pending_chunks table operations."""

    async def save(
        self,
        repo_id: str,
        chunks: List[Dict[str, Any]],
    ) -> int:
        """Save chunks to pending_chunks table using upsert.

        Uses INSERT ... ON CONFLICT DO UPDATE to handle re-ingestion and
        concurrent checkpoint saves without duplicate key violations.

        Args:
            repo_id: Repository identifier.
            chunks: List of chunk dictionaries with:
                - chunk_id: str
                - file_path: str
                - content: str
                - start_line: Optional[int]
                - end_line: Optional[int]
                - chunk_type: Optional[str]
                - language: Optional[str]
                - metadata_json: Optional[dict]
                - symbol_ids_json: Optional[list]

        Returns:
            Number of chunks saved.
        """
        import json

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Clear stale pending chunks from previous runs first.
        # This DELETE + INSERT is safe within a single transaction, but we
        # also use ON CONFLICT as a belt-and-suspenders guard against races
        # with concurrent sessions (e.g. checkpoint saves).
        await self._execute(delete(PendingChunk).where(PendingChunk.repo_id == repo_id))
        await self.session.flush()

        now = datetime.now(UTC)
        seen_chunk_ids: set[str] = set()
        rows: list[dict] = []

        for chunk_data in chunks:
            cid = chunk_data.get("chunk_id", "")
            if not cid or cid in seen_chunk_ids:
                continue
            seen_chunk_ids.add(cid)

            rows.append(
                {
                    "repo_id": repo_id,
                    "chunk_id": cid,
                    "file_path": chunk_data.get("file_path", ""),
                    "content": chunk_data.get("content", ""),
                    "start_line": chunk_data.get("start_line"),
                    "end_line": chunk_data.get("end_line"),
                    "chunk_type": chunk_data.get("chunk_type"),
                    "language": chunk_data.get("language"),
                    "metadata_json": json.dumps(chunk_data.get("metadata", {})),
                    "symbol_ids_json": json.dumps(chunk_data.get("symbol_ids", [])),
                    "created_at": now,
                }
            )

        if not rows:
            return 0

        # Batch upsert in chunks of 500 to avoid oversized SQL statements
        BATCH_SIZE = 500
        count = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            stmt = pg_insert(PendingChunk).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_pending_chunks_repo_chunk",
                set_={
                    "file_path": stmt.excluded.file_path,
                    "content": stmt.excluded.content,
                    "start_line": stmt.excluded.start_line,
                    "end_line": stmt.excluded.end_line,
                    "chunk_type": stmt.excluded.chunk_type,
                    "language": stmt.excluded.language,
                    "metadata_json": stmt.excluded.metadata_json,
                    "symbol_ids_json": stmt.excluded.symbol_ids_json,
                    "created_at": stmt.excluded.created_at,
                },
            )
            await self._execute(stmt)
            count += len(batch)

        await self.session.flush()
        logger.info(f"Saved {count} pending chunks for repo {repo_id}")
        return count

    async def get(self, repo_id: str) -> List[Dict[str, Any]]:
        """Get pending chunks for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            List of chunk dictionaries.
        """
        import json

        result = await self._execute(
            select(PendingChunk).where(PendingChunk.repo_id == repo_id).order_by(PendingChunk.id)
        )

        chunks = []
        for chunk in result.scalars().all():
            chunks.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "file_path": chunk.file_path,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type,
                    "language": chunk.language,
                    "metadata": json.loads(chunk.metadata_json) if chunk.metadata_json else {},
                    "symbol_ids": json.loads(chunk.symbol_ids_json) if chunk.symbol_ids_json else [],
                }
            )

        logger.info(f"Retrieved {len(chunks)} pending chunks for repo {repo_id}")
        return chunks

    async def count(self, repo_id: str) -> int:
        """Get count of pending chunks for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            Number of pending chunks.
        """
        result = await self._execute(
            select(func.count()).select_from(PendingChunk).where(PendingChunk.repo_id == repo_id)
        )
        return result.scalar() or 0

    async def clear(self, repo_id: str) -> int:
        """Clear all pending chunks for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            Number of chunks deleted.
        """
        result = await self._execute(delete(PendingChunk).where(PendingChunk.repo_id == repo_id))
        count = result.rowcount
        logger.info(f"Cleared {count} pending chunks for repo {repo_id}")
        return count

    async def has_pending(self, repo_id: str) -> bool:
        """Check if a repository has pending chunks.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if there are pending chunks, False otherwise.
        """
        return await self.count(repo_id) > 0


# =========================================================================
# Failed Embedding Chunks Table
# =========================================================================


class FailedEmbeddingChunksRepository(BaseRepository):
    """Repository for failed_embedding_chunks table operations."""

    async def save(
        self,
        repo_id: str,
        failed_chunks: List[Dict[str, Any]],
        errors: Dict[int, str],
    ) -> int:
        """Save chunks that failed embedding.

        Args:
            repo_id: Repository identifier.
            failed_chunks: List of chunk dictionaries.
            errors: Dict mapping chunk index to error message.

        Returns:
            Number of chunks saved.
        """
        import json

        now = datetime.now(UTC)
        count = 0

        for i, chunk_data in enumerate(failed_chunks):
            error_msg = errors.get(i, "Unknown error")

            # Check if chunk already exists
            existing = await self._execute(
                select(FailedEmbeddingChunk).where(
                    FailedEmbeddingChunk.repo_id == repo_id,
                    FailedEmbeddingChunk.chunk_id == chunk_data.get("chunk_id", ""),
                )
            )
            existing_chunk = existing.scalar_one_or_none()

            current_retry_count = existing_chunk.retry_count if existing_chunk else 0

            chunk = FailedEmbeddingChunk(
                repo_id=repo_id,
                chunk_id=chunk_data.get("chunk_id", ""),
                file_path=chunk_data.get("file_path", ""),
                content=chunk_data.get("content", ""),
                start_line=chunk_data.get("start_line"),
                end_line=chunk_data.get("end_line"),
                chunk_type=chunk_data.get("chunk_type"),
                language=chunk_data.get("language"),
                metadata_json=json.dumps(chunk_data.get("metadata", {})),
                symbol_ids_json=json.dumps([]),
                error_message=error_msg,
                retry_count=current_retry_count + 1,
                created_at=existing_chunk.created_at if existing_chunk else now,
                last_retry_at=now,
            )

            if existing_chunk:
                # Update
                await self._execute(
                    update(FailedEmbeddingChunk)
                    .where(FailedEmbeddingChunk.id == existing_chunk.id)
                    .values(
                        content=chunk.content,
                        chunk_type=chunk.chunk_type,
                        language=chunk.language,
                        metadata_json=chunk.metadata_json,
                        error_message=error_msg,
                        retry_count=current_retry_count + 1,
                        last_retry_at=now,
                    )
                )
            else:
                # Insert
                self.session.add(chunk)

            count += 1

        await self.session.flush()
        logger.info(f"Saved {count} failed embedding chunks for repo {repo_id}")
        return count

    async def get(self, repo_id: str, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Get failed chunks for retry.

        Args:
            repo_id: Repository identifier.
            max_retries: Maximum retry count to include.

        Returns:
            List of chunk dictionaries.
        """
        import json

        result = await self._execute(
            select(FailedEmbeddingChunk)
            .where(
                FailedEmbeddingChunk.repo_id == repo_id,
                FailedEmbeddingChunk.retry_count < max_retries,
            )
            .order_by(FailedEmbeddingChunk.id)
        )

        chunks = []
        for chunk in result.scalars().all():
            chunks.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "file_path": chunk.file_path,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type,
                    "language": chunk.language,
                    "metadata": json.loads(chunk.metadata_json) if chunk.metadata_json else {},
                    "error_message": chunk.error_message,
                    "retry_count": chunk.retry_count,
                }
            )

        return chunks

    async def count(self, repo_id: str) -> int:
        """Get count of failed chunks.

        Args:
            repo_id: Repository identifier.

        Returns:
            Number of failed chunks.
        """
        result = await self._execute(
            select(func.count()).select_from(FailedEmbeddingChunk).where(FailedEmbeddingChunk.repo_id == repo_id)
        )
        return result.scalar() or 0

    async def clear(self, repo_id: str, chunk_ids: Optional[List[str]] = None) -> int:
        """Clear failed chunks.

        Args:
            repo_id: Repository identifier.
            chunk_ids: Optional list of specific chunk IDs to clear.

        Returns:
            Number of chunks deleted.
        """
        if chunk_ids:
            # Clear specific chunks
            result = await self._execute(
                delete(FailedEmbeddingChunk).where(
                    FailedEmbeddingChunk.repo_id == repo_id,
                    FailedEmbeddingChunk.chunk_id.in_(chunk_ids),
                )
            )
        else:
            # Clear all
            result = await self._execute(delete(FailedEmbeddingChunk).where(FailedEmbeddingChunk.repo_id == repo_id))

        count = result.rowcount
        logger.info(f"Cleared {count} failed chunks for repo {repo_id}")
        return count

    async def has_failed(self, repo_id: str) -> bool:
        """Check if a repository has failed chunks.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if there are failed chunks, False otherwise.
        """
        return await self.count(repo_id) > 0

    async def get_stats(self, repo_id: str) -> Dict[str, Any]:
        """Get statistics about failed embedding chunks.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dict with total, by_retry_count, and common_errors.
        """
        total = await self.count(repo_id)

        # Count by retry
        result = await self._execute(
            select(
                FailedEmbeddingChunk.retry_count,
                func.count().label("count"),
            )
            .where(FailedEmbeddingChunk.repo_id == repo_id)
            .group_by(FailedEmbeddingChunk.retry_count)
            .order_by(FailedEmbeddingChunk.retry_count)
        )
        by_retry = {row[0]: row[1] for row in result.all()}

        # Common errors (top 5)
        result = await self._execute(
            select(
                FailedEmbeddingChunk.error_message,
                func.count().label("count"),
            )
            .where(FailedEmbeddingChunk.repo_id == repo_id)
            .group_by(FailedEmbeddingChunk.error_message)
            .order_by(func.count().desc())
            .limit(5)
        )
        common_errors = [(row[0], row[1]) for row in result.all()]

        return {
            "total": total,
            "by_retry_count": by_retry,
            "common_errors": common_errors,
        }


# =========================================================================
# Embedding Progress Table
# =========================================================================


class EmbeddingProgressRepository(BaseRepository):
    """Repository for embedding_progress table operations."""

    async def init(
        self,
        repo_id: str,
        total_chunks: int,
    ) -> None:
        """Initialize embedding progress.

        Args:
            repo_id: Repository identifier.
            total_chunks: Total number of chunks to embed.
        """
        now = datetime.now(UTC)

        progress = EmbeddingProgress(
            repo_id=repo_id,
            total_chunks=total_chunks,
            embedded_chunks=0,
            failed_chunks=0,
            skipped_chunks=0,
            current_chunk_idx=0,
            started_at=now,
            updated_at=now,
            status="in_progress",
        )

        self.session.add(progress)
        await self.session.flush()
        logger.info(f"Initialized embedding progress for {repo_id}: {total_chunks} chunks")

    async def update(
        self,
        repo_id: str,
        embedded_chunks: int,
        failed_chunks: int,
        current_chunk_idx: int,
        skipped_chunks: int = 0,
        status: str = "in_progress",
        error_message: Optional[str] = None,
    ) -> None:
        """Update embedding progress.

        Args:
            repo_id: Repository identifier.
            embedded_chunks: Number of successfully embedded chunks.
            failed_chunks: Number of failed chunks.
            current_chunk_idx: Current chunk index.
            skipped_chunks: Number of skipped chunks.
            status: Progress status.
            error_message: Optional error message.
        """
        now = datetime.now(UTC)
        await self._execute(
            update(EmbeddingProgress)
            .where(EmbeddingProgress.repo_id == repo_id)
            .values(
                embedded_chunks=embedded_chunks,
                failed_chunks=failed_chunks,
                current_chunk_idx=current_chunk_idx,
                skipped_chunks=skipped_chunks,
                status=status,
                error_message=error_message,
                updated_at=now,
            )
        )

    async def get(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Get embedding progress.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dictionary with progress info or None if not found.
        """
        result = await self._execute(select(EmbeddingProgress).where(EmbeddingProgress.repo_id == repo_id))
        progress = result.scalar_one_or_none()

        if not progress:
            return None

        return {
            "total_chunks": progress.total_chunks,
            "embedded_chunks": progress.embedded_chunks,
            "failed_chunks": progress.failed_chunks,
            "skipped_chunks": progress.skipped_chunks,
            "current_chunk_idx": progress.current_chunk_idx,
            "started_at": progress.started_at,
            "updated_at": progress.updated_at,
            "status": progress.status,
            "error_message": progress.error_message,
            "remaining_chunks": progress.total_chunks
            - progress.embedded_chunks
            - progress.failed_chunks
            - progress.skipped_chunks,
        }

    async def clear(self, repo_id: str) -> None:
        """Clear embedding progress for a repository.

        Args:
            repo_id: Repository identifier.
        """
        await self._execute(delete(EmbeddingProgress).where(EmbeddingProgress.repo_id == repo_id))
        logger.info(f"Cleared embedding progress for repo {repo_id}")


# =========================================================================
# Indexing Progress Table
# =========================================================================


class IndexingProgressRepository(BaseRepository):
    """Repository for indexing_progress table operations (live progress)."""

    async def save(
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
        """Save or update live indexing progress.

        Args:
            repo_id: Repository identifier.
            phase: Current indexing phase.
            total_files: Total files to process.
            processed_files: Files processed so far.
            current_file: Currently processing file.
            total_chunks: Total chunks created.
            total_symbols: Total symbols extracted.
            total_relationships: Total relationships created.
            embedded_chunks: Chunks embedded so far.
            total_chunks_to_embed: Total chunks to embed.
            message: Current status message.
        """
        now = datetime.now(UTC)

        # Check if exists (for update)
        existing = await self._execute(select(IndexingProgress).where(IndexingProgress.repo_id == repo_id))
        existing = existing.scalar_one_or_none()

        if existing:
            # Update
            await self._execute(
                update(IndexingProgress)
                .where(IndexingProgress.repo_id == repo_id)
                .values(
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
                    updated_at=now,
                )
            )
        else:
            # Insert
            progress = IndexingProgress(
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
                updated_at=now,
            )
            self.session.add(progress)

        await self.session.flush()

    async def get(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Get live indexing progress.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dictionary with progress information or None if not found.
        """
        result = await self._execute(select(IndexingProgress).where(IndexingProgress.repo_id == repo_id))
        progress = result.scalar_one_or_none()

        if not progress:
            return None

        return {
            "repo_id": repo_id,
            "phase": progress.phase,
            "total_files": progress.total_files,
            "processed_files": progress.processed_files,
            "current_file": progress.current_file,
            "total_chunks": progress.total_chunks,
            "total_symbols": progress.total_symbols,
            "total_relationships": progress.total_relationships,
            "embedded_chunks": progress.embedded_chunks,
            "total_chunks_to_embed": progress.total_chunks_to_embed,
            "message": progress.message,
            "updated_at": progress.updated_at,
        }

    async def delete(self, repo_id: str) -> None:
        """Delete indexing progress.

        Args:
            repo_id: Repository identifier.
        """
        await self._execute(delete(IndexingProgress).where(IndexingProgress.repo_id == repo_id))

    async def is_active(self, repo_id: str) -> bool:
        """Check if a repository has active indexing progress.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if there's active progress data, False otherwise.
        """
        result = await self._execute(
            select(IndexingProgress).where(
                IndexingProgress.repo_id == repo_id,
                IndexingProgress.phase.not_in_(["completed", "error", "paused"]),
            )
        )
        return result.scalar_one_or_none() is not None


# =========================================================================
# User Preferences Table
# =========================================================================


class UserPreferencesRepository(BaseRepository):
    """Repository for user_preferences table operations."""

    async def save(
        self,
        user_id: str,
        settings: Dict[str, Any],
    ) -> None:
        """Save user retrieval preferences.

        Args:
            user_id: User identifier (e.g., "default").
            settings: The settings dictionary to save.
        """
        now = datetime.now(UTC)

        # Check if exists
        existing = await self._execute(select(UserPreference).where(UserPreference.user_id == user_id))
        existing_pref = existing.scalar_one_or_none()

        if existing_pref:
            # Update
            await self._execute(
                update(UserPreference)
                .where(UserPreference.user_id == user_id)
                .values(
                    settings_json=settings,
                    updated_at=now,
                )
            )
        else:
            # Insert
            pref = UserPreference(
                user_id=user_id,
                settings_json=settings,
                created_at=now,
                updated_at=now,
            )
            self.session.add(pref)

        await self.session.flush()
        logger.info(f"Saved preferences for user: {user_id}")

    async def load(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load user retrieval preferences.

        Args:
            user_id: User identifier.

        Returns:
            Settings dictionary if found, None otherwise.
        """
        import json

        result = await self._execute(select(UserPreference).where(UserPreference.user_id == user_id))
        pref = result.scalar_one_or_none()

        if not pref:
            return None

        if not pref.settings_json:
            return {}
        # JSONB columns are auto-deserialized to dict by SQLAlchemy;
        # only call json.loads when the value is still a raw string.
        if isinstance(pref.settings_json, dict):
            return pref.settings_json
        return json.loads(pref.settings_json)

    async def delete(self, user_id: str) -> bool:
        """Delete user preferences.

        Args:
            user_id: User identifier.

        Returns:
            True if deleted, False if not found.
        """
        result = await self._execute(delete(UserPreference).where(UserPreference.user_id == user_id))
        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"Deleted preferences for user: {user_id}")
        return deleted
