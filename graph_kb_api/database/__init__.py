"""Database package for GraphKB API.

This package provides async PostgreSQL ORM and repository pattern:

- base: Engine configuration and session management
- models: SQLAlchemy ORM models
- repositories: Async repository classes

Usage:
    >>> from graph_kb_api.database import Base, get_session
    >>> from graph_kb_api.database.repositories import RepositoryRepository
    >>>
    >>> # In a FastAPI route
    >>> @router.get("/repos")
    >>> async def list_repos(db: AsyncSession = Depends(get_db_session)):
    >>>     repo_repo = RepositoryRepository(db)
    >>>     repos = await repo_repo.list()
    >>>     return repos
"""

from graph_kb_api.database.base import Base, get_session
from graph_kb_api.database.metadata_service import (
    AsyncMetadataService,
    SyncMetadataService,
)
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
from graph_kb_api.database.repositories import (
    BaseRepository,
    DocumentRepository,
    EmbeddingProgressRepository,
    FailedEmbeddingChunksRepository,
    FileIndexRepository,
    IndexingProgressRepository,
    PendingChunksRepository,
    RepositoryRepository,
    UserPreferencesRepository,
)

__all__ = [
    # Base and session
    "Base",
    "get_session",
    # Models
    "Repository",
    "Document",
    "FileIndex",
    "PendingChunk",
    "FailedEmbeddingChunk",
    "EmbeddingProgress",
    "IndexingProgress",
    "UserPreference",
    # Repositories
    "BaseRepository",
    "RepositoryRepository",
    "DocumentRepository",
    "FileIndexRepository",
    "PendingChunksRepository",
    "FailedEmbeddingChunksRepository",
    "EmbeddingProgressRepository",
    "IndexingProgressRepository",
    "UserPreferencesRepository",
    # Metadata service (replaces SQLite MetadataStore)
    "AsyncMetadataService",
    "SyncMetadataService",
]
