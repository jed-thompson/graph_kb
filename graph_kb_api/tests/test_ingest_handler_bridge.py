"""Tests for handle_ingest_workflow ThreadSafeBridge integration.

Validates that the ingest handler correctly wires ThreadSafeBridge and
consume_progress_queue for clone and indexing progress callbacks.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Lightweight stubs for IndexingPhase / IndexingProgress so we don't need
# the full dependency tree.
# ---------------------------------------------------------------------------


class _FakeIndexingPhase(Enum):
    INITIALIZING = "initializing"
    DISCOVERING_FILES = "discovering_files"
    INDEXING_FILES = "indexing_files"
    RESOLVING_RELATIONSHIPS = "resolving_relationships"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    BUILDING_GRAPH = "building_graph"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class _FakeIndexingProgress:
    repo_id: str = ""
    phase: _FakeIndexingPhase = _FakeIndexingPhase.INITIALIZING
    total_files: int = 0
    processed_files: int = 0
    current_file: Optional[str] = None
    total_chunks: int = 0
    total_symbols: int = 0
    total_relationships: int = 0
    message: str = ""
    progress_percent: float = 0.0


@dataclass
class _FakeRepoInfo:
    local_path: str = "/tmp/repo"
    commit_sha: str = "abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload():
    """Return a minimal IngestPayload-like object."""
    p = MagicMock()
    p.git_url = "https://github.com/example/repo.git"
    p.branch = "main"
    return p


def _make_facade(repo_exists: bool = False):
    facade = MagicMock()
    facade.repo_fetcher.create_repo_id.return_value = "repo-123"
    facade.repo_fetcher.repo_exists.return_value = repo_exists
    facade.repo_fetcher.clone_repo.return_value = _FakeRepoInfo()
    facade.repo_fetcher.update_repo.return_value = _FakeRepoInfo()

    result = _FakeIndexingProgress(
        repo_id="repo-123",
        phase=_FakeIndexingPhase.COMPLETED,
        total_files=10,
        total_chunks=50,
        total_symbols=30,
        total_relationships=20,
    )
    facade.ingestion_service.index_repo.return_value = result
    return facade


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIngestHandlerBridge:
    """Verify handle_ingest_workflow uses ThreadSafeBridge + consume_progress_queue."""

    @patch("graph_kb_api.websocket.handlers.manager", new_callable=AsyncMock)
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    async def test_creates_bridge_and_consumer(self, mock_facade_fn, mock_mgr):
        """The handler must create a ThreadSafeBridge and spawn consume_progress_queue."""
        mock_facade_fn.return_value = _make_facade()
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()

        with (
            patch(
                "graph_kb_api.graph_kb.models.enums.IndexingPhase",
                _FakeIndexingPhase,
            ),
            patch(
                "graph_kb_api.graph_kb.models.ingestion.IndexingProgress",
                _FakeIndexingProgress,
            ),
            patch(
                "asyncio.to_thread",
                new_callable=lambda: lambda *a, **kw: _async_to_thread_passthrough,
            ),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            payload = _make_payload()
            await handle_ingest_workflow("client-1", "wf-1", payload)

        # The finally block must send sentinel and complete workflow
        mock_mgr.complete_workflow.assert_awaited_once_with("wf-1")

    @patch("graph_kb_api.websocket.handlers.manager", new_callable=AsyncMock)
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    async def test_clone_progress_callback_passed(self, mock_facade_fn, mock_mgr):
        """clone_repo must receive a progress_callback keyword argument."""
        facade = _make_facade(repo_exists=False)
        mock_facade_fn.return_value = facade
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()

        with (
            patch(
                "graph_kb_api.graph_kb.models.enums.IndexingPhase",
                _FakeIndexingPhase,
            ),
            patch(
                "graph_kb_api.graph_kb.models.ingestion.IndexingProgress",
                _FakeIndexingProgress,
            ),
            patch(
                "asyncio.to_thread",
                side_effect=_to_thread_side_effect,
            ),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            payload = _make_payload()
            await handle_ingest_workflow("client-1", "wf-1", payload)

        # clone_repo must have been called with progress_callback
        call_kwargs = facade.repo_fetcher.clone_repo.call_args
        assert call_kwargs is not None, "clone_repo was not called"
        assert "progress_callback" in (call_kwargs.kwargs or {}), (
            "clone_repo was not called with progress_callback keyword"
        )
        assert callable(call_kwargs.kwargs["progress_callback"])

    @patch("graph_kb_api.websocket.handlers.manager", new_callable=AsyncMock)
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    async def test_index_progress_callback_passed(self, mock_facade_fn, mock_mgr):
        """index_repo must receive a progress_callback keyword argument."""
        facade = _make_facade(repo_exists=False)
        mock_facade_fn.return_value = facade
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()

        with (
            patch(
                "graph_kb_api.graph_kb.models.enums.IndexingPhase",
                _FakeIndexingPhase,
            ),
            patch(
                "graph_kb_api.graph_kb.models.ingestion.IndexingProgress",
                _FakeIndexingProgress,
            ),
            patch(
                "asyncio.to_thread",
                side_effect=_to_thread_side_effect,
            ),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            payload = _make_payload()
            await handle_ingest_workflow("client-1", "wf-1", payload)

        call_kwargs = facade.ingestion_service.index_repo.call_args
        assert call_kwargs is not None, "index_repo was not called"
        assert "progress_callback" in (call_kwargs.kwargs or {}), (
            "index_repo was not called with progress_callback keyword"
        )
        assert callable(call_kwargs.kwargs["progress_callback"])

    @patch("graph_kb_api.websocket.handlers.manager", new_callable=AsyncMock)
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    async def test_sentinel_sent_on_error(self, mock_facade_fn, mock_mgr):
        """On exception, the finally block must still send sentinel and await consumer."""
        facade = _make_facade()
        facade.ingestion_service = None  # triggers RuntimeError
        mock_facade_fn.return_value = facade
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()

        with (
            patch(
                "graph_kb_api.graph_kb.models.enums.IndexingPhase",
                _FakeIndexingPhase,
            ),
            patch(
                "graph_kb_api.graph_kb.models.ingestion.IndexingProgress",
                _FakeIndexingProgress,
            ),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            payload = _make_payload()
            await handle_ingest_workflow("client-1", "wf-1", payload)

        # Error event should have been sent
        error_calls = [
            c
            for c in mock_mgr.send_event.call_args_list
            if c.kwargs.get("event_type") == "error"
        ]
        assert len(error_calls) == 1
        assert "WORKFLOW_ERROR" in str(error_calls[0])

        # complete_workflow must still be called (from finally)
        mock_mgr.complete_workflow.assert_awaited_once_with("wf-1")

    @patch("graph_kb_api.websocket.handlers.manager", new_callable=AsyncMock)
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    async def test_complete_event_sent_on_success(self, mock_facade_fn, mock_mgr):
        """On success, a 'complete' event with repo stats must be sent."""
        mock_facade_fn.return_value = _make_facade()
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()

        with (
            patch(
                "graph_kb_api.graph_kb.models.enums.IndexingPhase",
                _FakeIndexingPhase,
            ),
            patch(
                "graph_kb_api.graph_kb.models.ingestion.IndexingProgress",
                _FakeIndexingProgress,
            ),
            patch(
                "asyncio.to_thread",
                side_effect=_to_thread_side_effect,
            ),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            payload = _make_payload()
            await handle_ingest_workflow("client-1", "wf-1", payload)

        complete_calls = [
            c
            for c in mock_mgr.send_event.call_args_list
            if c.kwargs.get("event_type") == "complete"
        ]
        assert len(complete_calls) == 1
        data = complete_calls[0].kwargs["data"]
        assert data["repo_id"] == "repo-123"
        assert "stats" in data
        assert data["stats"]["total_files"] == 10


# ---------------------------------------------------------------------------
# Helpers for asyncio.to_thread patching
# ---------------------------------------------------------------------------


async def _async_to_thread_passthrough(fn, *args, **kwargs):
    """Call fn synchronously (no real thread) for test simplicity."""
    return fn(*args, **kwargs)


async def _to_thread_side_effect(fn, *args, **kwargs):
    """Simulate asyncio.to_thread by calling fn directly."""
    return fn(*args, **kwargs)
