"""
Unit tests for the AsyncMetadataService and SyncMetadataService.

Validates the PostgreSQL-backed metadata service that replaced the
old SQLite MetadataStore.  Uses a mocked async session factory so
no real database is needed.

NOTE: We use lazy imports (inside each test class / function) to avoid
a circular-import error that occurs when ``graph_kb_api.database.metadata_service``
is imported at module level during pytest collection.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Helpers — lightweight ORM fakes
# ---------------------------------------------------------------------------


def _fake_repo_orm(
    repo_id="repo-1",
    git_url="https://github.com/org/repo",
    default_branch="main",
    local_path="/data/repos/repo-1",
    last_indexed_commit=None,
    last_indexed_at=None,
    status="ready",
    error_message=None,
):
    return SimpleNamespace(
        repo_id=repo_id,
        git_url=git_url,
        default_branch=default_branch,
        local_path=local_path,
        last_indexed_commit=last_indexed_commit,
        last_indexed_at=last_indexed_at,
        status=status,
        error_message=error_message,
    )


def _fake_doc_orm(
    doc_id="doc-1",
    original_name="readme.md",
    file_path="/docs/readme.md",
    parent_name=None,
    category="docs",
    collection_name="default",
    file_hash="abc123",
    chunk_count=5,
    status="completed",
    error_message=None,
):
    return SimpleNamespace(
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
    )


def _fake_file_orm(
    repo_id="repo-1",
    file_path="src/main.py",
    file_hash="def456",
    status="completed",
    chunk_count=3,
    symbol_count=2,
    error_message=None,
    indexed_at=None,
):
    return SimpleNamespace(
        repo_id=repo_id,
        file_path=file_path,
        file_hash=file_hash,
        status=status,
        chunk_count=chunk_count,
        symbol_count=symbol_count,
        error_message=error_message,
        indexed_at=indexed_at,
    )


def _import_ms():
    """Lazy import to break circular dependency at collection time."""
    from graph_kb_api.database.metadata_service import (
        AsyncMetadataService,
        SyncMetadataService,
        _orm_doc_to_domain,
        _orm_file_to_domain,
        _orm_repo_to_domain,
    )

    return (
        AsyncMetadataService,
        SyncMetadataService,
        _orm_repo_to_domain,
        _orm_doc_to_domain,
        _orm_file_to_domain,
    )


# ---------------------------------------------------------------------------
# Async session factory mock
# ---------------------------------------------------------------------------


class FakeSession:
    """Minimal async context-manager session mock."""

    def __init__(self):
        self.committed = False
        self.closed = False

    async def commit(self):
        self.committed = True

    async def close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def _make_session_factory(session=None):
    s = session or FakeSession()

    def factory():
        return s

    return factory


# ---------------------------------------------------------------------------
# ORM → Domain converters
# ---------------------------------------------------------------------------


class TestOrmToDomainConverters:
    def test_orm_repo_to_domain(self):
        _, _, to_repo, _, _ = _import_ms()
        orm = _fake_repo_orm(status="ready")
        domain = to_repo(orm)
        assert domain.repo_id == "repo-1"
        assert domain.git_url == "https://github.com/org/repo"
        assert domain.default_branch == "main"
        assert domain.status.value == "ready"

    def test_orm_repo_to_domain_with_error(self):
        _, _, to_repo, _, _ = _import_ms()
        orm = _fake_repo_orm(status="error", error_message="boom")
        domain = to_repo(orm)
        assert domain.status.value == "error"
        assert domain.error_message == "boom"

    def test_orm_doc_to_domain(self):
        _, _, _, to_doc, _ = _import_ms()
        orm = _fake_doc_orm()
        domain = to_doc(orm)
        assert domain.doc_id == "doc-1"
        assert domain.original_name == "readme.md"
        assert domain.chunk_count == 5
        assert domain.status.value == "completed"

    def test_orm_file_to_domain(self):
        _, _, _, _, to_file = _import_ms()
        orm = _fake_file_orm()
        domain = to_file(orm)
        assert domain.repo_id == "repo-1"
        assert domain.file_path == "src/main.py"
        assert domain.chunk_count == 3
        assert domain.symbol_count == 2
        assert domain.status.value == "completed"

    def test_orm_file_to_domain_null_counts(self):
        _, _, _, _, to_file = _import_ms()
        orm = _fake_file_orm(chunk_count=None, symbol_count=None)
        domain = to_file(orm)
        assert domain.chunk_count == 0
        assert domain.symbol_count == 0


# ---------------------------------------------------------------------------
# AsyncMetadataService — Repos
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceRepos:
    async def test_get_repo_returns_domain_model(self):
        AsyncMS, *_ = _import_ms()
        orm_obj = _fake_repo_orm()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.get = AsyncMock(return_value=orm_obj)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_repo("repo-1")
        assert result is not None
        assert result.repo_id == "repo-1"
        assert result.status.value == "ready"

    async def test_get_repo_returns_none_when_missing(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.get = AsyncMock(return_value=None)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_repo("nonexistent")
        assert result is None

    async def test_list_repos_returns_domain_list(self):
        AsyncMS, *_ = _import_ms()
        orm_list = [_fake_repo_orm(repo_id="r1"), _fake_repo_orm(repo_id="r2")]
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.list = AsyncMock(return_value=orm_list)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.list_repos()
        assert len(result) == 2
        assert result[0].repo_id == "r1"

    async def test_delete_repo_commits(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.delete = AsyncMock(return_value=True)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.delete_repo("repo-1")
        assert result is True
        assert session.committed

    async def test_repo_exists_delegates(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.exists = AsyncMock(return_value=True)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.repo_exists("repo-1") is True

    async def test_count_repos_delegates(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.RepositoryRepository") as M:
            M.return_value.count = AsyncMock(return_value=42)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.count_repos() == 42

    async def test_get_repository_alias(self):
        AsyncMS, *_ = _import_ms()
        # Class-level alias: bound methods won't be ``is`` identical,
        # but the underlying function should be the same.
        assert AsyncMS.get_repository is AsyncMS.get_repo

    async def test_delete_repository_alias(self):
        AsyncMS, *_ = _import_ms()
        assert AsyncMS.delete_repository is AsyncMS.delete_repo


# ---------------------------------------------------------------------------
# AsyncMetadataService — Documents
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceDocuments:
    async def test_get_document_returns_domain(self):
        AsyncMS, *_ = _import_ms()
        orm_obj = _fake_doc_orm()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.DocumentRepository") as M:
            M.return_value.get = AsyncMock(return_value=orm_obj)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_document("doc-1")
        assert result is not None
        assert result.doc_id == "doc-1"
        assert result.status.value == "completed"

    async def test_get_document_returns_none(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.DocumentRepository") as M:
            M.return_value.get = AsyncMock(return_value=None)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.get_document("missing") is None

    async def test_count_documents_delegates(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.DocumentRepository") as M:
            M.return_value.count = AsyncMock(return_value=7)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.count_documents() == 7

    async def test_list_documents_passes_parent_name_filter(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.DocumentRepository") as M:
            M.return_value.list = AsyncMock(return_value=[])
            svc = AsyncMS(_make_session_factory(session))
            await svc.list_documents(parent_name="plan-session-1")

        M.return_value.list.assert_awaited_once_with(
            parent_name="plan-session-1",
            status=None,
            category=None,
            collection_name=None,
            limit=100,
            offset=0,
        )


# ---------------------------------------------------------------------------
# AsyncMetadataService — File Index
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceFileIndex:
    async def test_get_file_status_returns_domain(self):
        AsyncMS, *_ = _import_ms()
        orm_obj = _fake_file_orm()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.FileIndexRepository") as M:
            M.return_value.get = AsyncMock(return_value=orm_obj)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_file_status("repo-1", "src/main.py")
        assert result is not None
        assert result.file_path == "src/main.py"

    async def test_get_processed_files_delegates(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.FileIndexRepository") as M:
            M.return_value.get_processed_files = AsyncMock(
                return_value={"a.py", "b.py"}
            )
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_processed_files("repo-1")
        assert result == {"a.py", "b.py"}

    async def test_mark_file_completed_commits(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch("graph_kb_api.database.metadata_service.FileIndexRepository") as M:
            M.return_value.mark_completed = AsyncMock()
            svc = AsyncMS(_make_session_factory(session))
            await svc.mark_file_completed("repo-1", "a.py", "hash1", 5, 3)
        assert session.committed
        M.return_value.mark_completed.assert_awaited_once_with(
            "repo-1", "a.py", "hash1", 5, 3
        )


# ---------------------------------------------------------------------------
# AsyncMetadataService — Preferences
# ---------------------------------------------------------------------------


class TestAsyncMetadataServicePreferences:
    async def test_load_raw_preferences(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        data = {"model": "gpt-4o", "temperature": 0.5}
        with patch(
            "graph_kb_api.database.metadata_service.UserPreferencesRepository"
        ) as M:
            M.return_value.load = AsyncMock(return_value=data)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.load_raw_preferences("default:extra")
        assert result == data

    async def test_save_raw_preferences_commits(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.UserPreferencesRepository"
        ) as M:
            M.return_value.save = AsyncMock()
            svc = AsyncMS(_make_session_factory(session))
            await svc.save_raw_preferences("user1", {"key": "val"})
        assert session.committed
        M.return_value.save.assert_awaited_once_with("user1", {"key": "val"})

    async def test_delete_user_preferences(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.UserPreferencesRepository"
        ) as M:
            M.return_value.delete = AsyncMock(return_value=True)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.delete_user_preferences("user1") is True


# ---------------------------------------------------------------------------
# AsyncMetadataService — Embedding Progress
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceEmbeddingProgress:
    async def test_get_embedding_progress(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        progress = {"total_chunks": 100, "embedded_chunks": 50}
        with patch(
            "graph_kb_api.database.metadata_service.EmbeddingProgressRepository"
        ) as M:
            M.return_value.get = AsyncMock(return_value=progress)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_embedding_progress("repo-1")
        assert result == progress

    async def test_init_embedding_progress_commits(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.EmbeddingProgressRepository"
        ) as M:
            M.return_value.init = AsyncMock()
            svc = AsyncMS(_make_session_factory(session))
            await svc.init_embedding_progress("repo-1", 200)
        assert session.committed


# ---------------------------------------------------------------------------
# AsyncMetadataService — Pending Chunks
# ---------------------------------------------------------------------------


class TestAsyncMetadataServicePendingChunks:
    async def test_get_pending_chunks_count(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.PendingChunksRepository"
        ) as M:
            M.return_value.count = AsyncMock(return_value=15)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.get_pending_chunks_count("repo-1") == 15

    async def test_has_pending_chunks(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.PendingChunksRepository"
        ) as M:
            M.return_value.has_pending = AsyncMock(return_value=True)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.has_pending_chunks("repo-1") is True

    async def test_clear_pending_chunks_commits(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.PendingChunksRepository"
        ) as M:
            M.return_value.clear = AsyncMock(return_value=10)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.clear_pending_chunks("repo-1")
        assert result == 10
        assert session.committed


# ---------------------------------------------------------------------------
# AsyncMetadataService — Indexing Progress
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceIndexingProgress:
    async def test_get_indexing_progress(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        data = {"phase": "embedding", "total_files": 50}
        with patch(
            "graph_kb_api.database.metadata_service.IndexingProgressRepository"
        ) as M:
            M.return_value.get = AsyncMock(return_value=data)
            svc = AsyncMS(_make_session_factory(session))
            result = await svc.get_indexing_progress("repo-1")
        assert result == data

    async def test_is_repo_actively_indexing(self):
        AsyncMS, *_ = _import_ms()
        session = FakeSession()
        with patch(
            "graph_kb_api.database.metadata_service.IndexingProgressRepository"
        ) as M:
            M.return_value.is_active = AsyncMock(return_value=False)
            svc = AsyncMS(_make_session_factory(session))
            assert await svc.is_repo_actively_indexing("repo-1") is False


# ---------------------------------------------------------------------------
# AsyncMetadataService — Lifecycle
# ---------------------------------------------------------------------------


class TestAsyncMetadataServiceLifecycle:
    async def test_close_is_noop(self):
        AsyncMS, *_ = _import_ms()
        svc = AsyncMS(_make_session_factory())
        await svc.close()  # should not raise


# ---------------------------------------------------------------------------
# SyncMetadataService
# ---------------------------------------------------------------------------


class TestSyncMetadataService:
    def test_creates_background_loop(self):
        AsyncMS, SyncMS, to_repo, _, _ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        sync_svc = SyncMS(async_svc)
        assert sync_svc._loop is not None
        assert sync_svc._loop.is_running()
        sync_svc.close()

    def test_delegates_get_repo(self):
        AsyncMS, SyncMS, to_repo, _, _ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        domain = to_repo(_fake_repo_orm())
        async_svc.get_repo = AsyncMock(return_value=domain)
        sync_svc = SyncMS(async_svc)
        result = sync_svc.get_repo("repo-1")
        assert result.repo_id == "repo-1"
        async_svc.get_repo.assert_awaited_once_with("repo-1")
        sync_svc.close()

    def test_delegates_list_repos(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        async_svc.list_repos = AsyncMock(return_value=[])
        sync_svc = SyncMS(async_svc)
        assert sync_svc.list_repos() == []
        sync_svc.close()

    def test_delegates_delete_repo(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        async_svc.delete_repo = AsyncMock(return_value=True)
        sync_svc = SyncMS(async_svc)
        assert sync_svc.delete_repo("repo-1") is True
        sync_svc.close()

    def test_get_repository_alias(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        assert SyncMS.get_repository is SyncMS.get_repo

    def test_delete_repository_alias(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        assert SyncMS.delete_repository is SyncMS.delete_repo

    def test_delegates_load_raw_preferences(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        async_svc.load_raw_preferences = AsyncMock(return_value={"k": "v"})
        sync_svc = SyncMS(async_svc)
        assert sync_svc.load_raw_preferences("user1") == {"k": "v"}
        sync_svc.close()

    def test_delegates_save_raw_preferences(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        async_svc = AsyncMock(spec=AsyncMS)
        async_svc.save_raw_preferences = AsyncMock()
        sync_svc = SyncMS(async_svc)
        sync_svc.save_raw_preferences("user1", {"k": "v"})
        async_svc.save_raw_preferences.assert_awaited_once_with("user1", {"k": "v"})
        sync_svc.close()

    def test_close_stops_loop(self):
        AsyncMS, SyncMS, *_ = _import_ms()
        sync_svc = SyncMS(AsyncMock(spec=AsyncMS))
        assert sync_svc._loop.is_running()
        sync_svc.close()
        time.sleep(0.1)
        assert not sync_svc._loop.is_running()


# ---------------------------------------------------------------------------
# Backward compatibility — storage re-export
# ---------------------------------------------------------------------------


class TestBackwardCompatReExport:
    def test_metadata_store_is_sync_service(self):
        _, SyncMS, *_ = _import_ms()
        from graph_kb_api.graph_kb.storage import MetadataStore

        assert MetadataStore is SyncMS

    def test_exception_classes_importable(self):
        from graph_kb_api.graph_kb.storage import (
            InvalidStatusTransitionError,
            MetadataStoreError,
            RepoNotFoundError,
        )

        assert issubclass(RepoNotFoundError, MetadataStoreError)
        assert issubclass(InvalidStatusTransitionError, MetadataStoreError)
