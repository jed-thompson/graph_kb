"""
Unit tests for the /ingest command pipeline.

Tests each stage of the ingest flow in isolation:
1. Payload parsing and routing
2. Repo fetcher (clone/update)
3. File discovery and indexing
4. Progress bridge and consumer
5. Error handling and edge cases

These tests mock all external dependencies (Neo4j, ChromaDB, PostgreSQL)
and focus on logic correctness.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fake / stub classes
# ---------------------------------------------------------------------------


@dataclass
class FakeRepoInfo:
    repo_id: str = "owner__repo"
    local_path: str = "/data/repos/owner__repo"
    commit_sha: str = "abc1234567890"
    branch: str = "main"
    git_url: str = "https://github.com/owner/repo.git"


class FakeIndexingPhase:
    INITIALIZING = "initializing"
    DISCOVERING_FILES = "discovering"
    INDEXING_FILES = "indexing"
    RESOLVING_RELATIONSHIPS = "resolving"
    GENERATING_EMBEDDINGS = "embedding"
    BUILDING_GRAPH = "building"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class FakeIndexingProgress:
    repo_id: str = "owner__repo"
    phase: str = "completed"
    total_files: int = 10
    processed_files: int = 10
    total_chunks: int = 50
    total_symbols: int = 30
    total_relationships: int = 20
    message: str = "Completed"
    current_file: Optional[str] = None
    progress_percent: float = 100.0
    processed_chunks: int = 50
    total_chunks_to_embed: int = 50
    resolved_files: int = 10
    total_files_to_resolve: int = 10
    failed_files: int = 0


# ---------------------------------------------------------------------------
# 1. Payload Parsing Tests
# ---------------------------------------------------------------------------


class TestPayloadParsing:
    """Test that ingest payloads are correctly parsed from WebSocket messages."""

    def test_ingest_payload_valid(self):
        from graph_kb_api.websocket.protocol import IngestPayload

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )
        assert payload.git_url == "https://github.com/owner/repo.git"
        assert payload.branch == "main"
        assert payload.force_reindex is False

    def test_ingest_payload_default_branch(self):
        from graph_kb_api.websocket.protocol import IngestPayload

        payload = IngestPayload(git_url="https://github.com/owner/repo.git")
        assert payload.branch == "main"

    def test_ingest_payload_missing_git_url_raises(self):
        from pydantic import ValidationError

        from graph_kb_api.websocket.protocol import IngestPayload

        with pytest.raises(ValidationError):
            IngestPayload()

    def test_ingest_payload_with_extra_fields_ignored(self):
        """Pydantic should ignore extra fields like workflow_type."""
        from graph_kb_api.websocket.protocol import IngestPayload

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="develop",
            workflow_type="ingest",  # extra field from WSStartPayload
        )
        assert payload.git_url == "https://github.com/owner/repo.git"
        assert payload.branch == "develop"

    def test_ws_start_payload_accepts_ingest_type(self):
        from graph_kb_api.schemas.websocket import WSStartPayload

        payload = WSStartPayload(workflow_type="ingest")
        assert payload.workflow_type == "ingest"

    def test_client_message_start_type(self):
        from graph_kb_api.websocket.protocol import ClientMessage

        msg = ClientMessage(
            type="start",
            payload={
                "workflow_type": "ingest",
                "git_url": "https://github.com/owner/repo.git",
                "branch": "main",
            },
        )
        assert msg.type == "start"
        assert msg.payload["git_url"] == "https://github.com/owner/repo.git"

    def test_full_message_flow_payload_preserved(self):
        """Simulate the full message flow: ClientMessage -> WSStartPayload -> IngestPayload.

        This is the critical path: the raw payload dict must survive through
        WSStartPayload validation and still contain git_url for IngestPayload.
        """
        from graph_kb_api.schemas.websocket import WSStartPayload
        from graph_kb_api.websocket.protocol import ClientMessage, IngestPayload

        raw_message = {
            "type": "start",
            "payload": {
                "workflow_type": "ingest",
                "git_url": "https://github.com/owner/repo.git",
                "branch": "develop",
            },
        }

        # Step 1: Parse as ClientMessage
        msg = ClientMessage(**raw_message)
        payload_dict = msg.payload

        # Step 2: Validate workflow_type via WSStartPayload
        start_payload = WSStartPayload(**payload_dict)
        assert start_payload.workflow_type == "ingest"

        # Step 3: Create IngestPayload from the SAME dict
        # This is what _handle_start does — it uses the raw payload dict
        ingest_payload = IngestPayload(**payload_dict)
        assert ingest_payload.git_url == "https://github.com/owner/repo.git"
        assert ingest_payload.branch == "develop"


# ---------------------------------------------------------------------------
# 2. Repo Fetcher Tests
# ---------------------------------------------------------------------------


class TestRepoFetcher:
    """Test GitRepoFetcher URL validation, repo_id creation, and clone logic."""

    def _make_fetcher(self, tmp_path: Path):
        from graph_kb_api.graph_kb.repositories.repo_fetcher import GitRepoFetcher

        return GitRepoFetcher(storage_path=str(tmp_path))

    def test_validate_url_valid_https(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        owner, name = fetcher.validate_url("https://github.com/owner/repo")
        assert owner == "owner"
        assert name == "repo"

    def test_validate_url_valid_with_git_suffix(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        owner, name = fetcher.validate_url("https://github.com/owner/repo.git")
        assert owner == "owner"
        assert name == "repo"

    def test_validate_url_invalid_raises(self, tmp_path):
        from graph_kb_api.graph_kb.repositories.repo_fetcher import InvalidURLError

        fetcher = self._make_fetcher(tmp_path)
        with pytest.raises(InvalidURLError):
            fetcher.validate_url("not-a-url")

    def test_create_repo_id_deterministic(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        id1 = fetcher.create_repo_id("https://github.com/owner/repo.git")
        id2 = fetcher.create_repo_id("https://github.com/owner/repo.git")
        assert id1 == id2

    def test_create_repo_id_strips_git_suffix(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        id1 = fetcher.create_repo_id("https://github.com/owner/repo.git")
        id2 = fetcher.create_repo_id("https://github.com/owner/repo")
        assert id1 == id2

    def test_repo_exists_false_when_no_dir(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        assert fetcher.repo_exists("nonexistent__repo") is False

    def test_get_repo_path_returns_path(self, tmp_path):
        fetcher = self._make_fetcher(tmp_path)
        path = fetcher.get_repo_path("owner__repo")
        assert isinstance(path, Path)
        assert "owner__repo" in str(path)


# ---------------------------------------------------------------------------
# 3. Progress Bridge Tests
# ---------------------------------------------------------------------------


class TestProgressBridge:
    """Test ThreadSafeBridge and ProgressEvent."""

    def test_progress_event_to_send_data(self):
        from graph_kb_api.websocket.progress import ProgressEvent

        event = ProgressEvent(
            phase="cloning",
            message="Cloning repo...",
            progress_percent=50.0,
        )
        data = event.to_send_data()
        assert data["phase"] == "cloning"
        assert data["message"] == "Cloning repo..."
        assert data["progress_percent"] == 50.0

    def test_progress_event_with_detail(self):
        from graph_kb_api.websocket.progress import ProgressEvent

        event = ProgressEvent(
            phase="indexing",
            message="Indexing files...",
            progress_percent=25.0,
            detail={"total_files": 100, "processed_files": 25},
        )
        data = event.to_send_data()
        # detail is merged into the result dict, not nested
        assert data["total_files"] == 100
        assert data["processed_files"] == 25

    @pytest.mark.asyncio
    async def test_bridge_sends_to_queue(self):
        """ThreadSafeBridge.send() should put events on the async queue."""
        from graph_kb_api.websocket.progress import ThreadSafeBridge

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

        bridge.send({"phase": "cloning", "message": "test"})

        # Give the event loop a chance to process
        await asyncio.sleep(0.05)

        assert not queue.empty()
        event = queue.get_nowait()
        assert event["phase"] == "cloning"

    @pytest.mark.asyncio
    async def test_bridge_stats_tracking(self):
        from graph_kb_api.websocket.progress import ThreadSafeBridge

        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

        for i in range(5):
            bridge.send({"phase": "test", "idx": i})

        await asyncio.sleep(0.05)
        stats = bridge.get_stats()
        assert stats["events_sent"] == 5
        assert stats["events_dropped"] == 0


# ---------------------------------------------------------------------------
# 4. Progress Consumer Tests
# ---------------------------------------------------------------------------


class TestProgressConsumer:
    """Test consume_progress_queue behavior."""

    @pytest.mark.asyncio
    async def test_consumer_stops_on_sentinel(self):
        from graph_kb_api.websocket.progress import consume_progress_queue

        queue = asyncio.Queue()
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)

        # Put some events then sentinel
        await queue.put({"phase": "cloning", "message": "test"})
        await queue.put(None)  # sentinel

        await consume_progress_queue(queue, "client-1", "wf-1", mock_manager)

        assert mock_manager.send_event.await_count == 1

    @pytest.mark.asyncio
    async def test_consumer_handles_send_failure(self):
        from graph_kb_api.websocket.progress import consume_progress_queue

        queue = asyncio.Queue()
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=False)  # send fails

        await queue.put({"phase": "cloning", "message": "test"})
        await queue.put(None)

        # Should not raise even when send fails
        await consume_progress_queue(queue, "client-1", "wf-1", mock_manager)

    @pytest.mark.asyncio
    async def test_consumer_processes_multiple_events(self):
        from graph_kb_api.websocket.progress import consume_progress_queue

        queue = asyncio.Queue()
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)

        for i in range(10):
            await queue.put({"phase": "indexing", "idx": i})
        await queue.put(None)

        await consume_progress_queue(queue, "client-1", "wf-1", mock_manager)

        assert mock_manager.send_event.await_count == 10


# ---------------------------------------------------------------------------
# 5. Connection Manager Tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    """Test ConnectionManager workflow management."""

    @pytest.mark.asyncio
    async def test_create_workflow_returns_id(self):
        from graph_kb_api.websocket.manager import ConnectionManager

        mgr = ConnectionManager()
        wf_id = mgr.create_workflow("client-1", "ingest")
        assert wf_id is not None
        assert len(wf_id) > 0

    @pytest.mark.asyncio
    async def test_get_workflow(self):
        from graph_kb_api.websocket.manager import ConnectionManager

        mgr = ConnectionManager()
        wf_id = mgr.create_workflow("client-1", "ingest")
        wf = mgr.get_workflow(wf_id)
        assert wf is not None
        assert wf.workflow_type == "ingest"
        assert wf.client_id == "client-1"
        assert wf.status == "running"

    @pytest.mark.asyncio
    async def test_complete_workflow(self):
        from graph_kb_api.websocket.manager import ConnectionManager

        mgr = ConnectionManager()
        wf_id = mgr.create_workflow("client-1", "ingest")
        await mgr.complete_workflow(wf_id)
        wf = mgr.get_workflow(wf_id)
        assert wf.status == "complete"

    @pytest.mark.asyncio
    async def test_send_event_returns_false_for_unknown_client(self):
        from graph_kb_api.websocket.manager import ConnectionManager

        mgr = ConnectionManager()
        result = await mgr.send_event(
            client_id="unknown",
            event_type="progress",
            workflow_id="wf-1",
            data={"phase": "test"},
        )
        assert result is False


# ---------------------------------------------------------------------------
# 6. Handle Ingest Workflow — Full Mock Tests
# ---------------------------------------------------------------------------


class TestHandleIngestWorkflow:
    """Test the handle_ingest_workflow function with fully mocked dependencies."""

    def _make_mock_facade(self, repo_exists=False):
        facade = MagicMock()

        # Mock repo_fetcher
        repo_fetcher = MagicMock()
        repo_fetcher.create_repo_id.return_value = "owner__repo"
        repo_fetcher.repo_exists.return_value = repo_exists
        repo_fetcher.clone_repo.return_value = FakeRepoInfo()
        repo_fetcher.update_repo.return_value = FakeRepoInfo()
        facade.repo_fetcher = repo_fetcher

        # Mock ingestion_service
        ingestion_service = MagicMock()
        ingestion_service.index_repo.return_value = FakeIndexingProgress()
        facade.ingestion_service = ingestion_service

        return facade

    @pytest.mark.asyncio
    async def test_successful_ingest_sends_complete_event(self):
        """Full happy path: clone -> index -> complete event."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade()
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)
        mock_manager.complete_workflow = AsyncMock()

        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            sent_events.append(kwargs)
            return True

        mock_manager.send_event = capture_send_event

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        # Should have progress events and a complete event
        event_types = [e.get("event_type") for e in sent_events]
        assert "progress" in event_types, f"No progress events found in: {event_types}"
        assert "complete" in event_types, f"No complete event found in: {event_types}"

        # Verify clone was called
        facade.repo_fetcher.clone_repo.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_calls_update_when_repo_exists(self):
        """When repo already exists locally, should call update_repo instead of clone_repo."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade(repo_exists=True)
        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        facade.repo_fetcher.update_repo.assert_called_once()
        facade.repo_fetcher.clone_repo.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_error_sends_error_event(self):
        """When clone fails, should send error event."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade()
        facade.repo_fetcher.clone_repo.side_effect = RuntimeError("Clone failed!")

        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            sent_events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = capture_send_event
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        event_types = [e.get("event_type") for e in sent_events]
        assert "error" in event_types, f"No error event found in: {event_types}"

        error_event = next(e for e in sent_events if e.get("event_type") == "error")
        assert "Clone failed!" in error_event["data"]["message"]

    @pytest.mark.asyncio
    async def test_ingest_no_ingestion_service_sends_error(self):
        """When ingestion_service is None, should send error."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade()
        facade.ingestion_service = None

        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            sent_events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = capture_send_event
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        event_types = [e.get("event_type") for e in sent_events]
        assert "error" in event_types

    @pytest.mark.asyncio
    async def test_ingest_no_repo_fetcher_sends_error(self):
        """When repo_fetcher is None, should send error."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade()
        facade.repo_fetcher = None

        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            sent_events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = capture_send_event
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        event_types = [e.get("event_type") for e in sent_events]
        assert "error" in event_types

    @pytest.mark.asyncio
    async def test_bridge_sentinel_always_sent_in_finally(self):
        """The finally block must always send sentinel and complete workflow."""
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = self._make_mock_facade()
        facade.repo_fetcher.clone_repo.side_effect = RuntimeError("Boom!")

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/owner/repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch(
                "graph_kb_api.websocket.handlers.manager",
                mock_manager,
            ),
            patch("asyncio.to_thread", side_effect=self._passthrough_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("client-1", "wf-1", payload)

        mock_manager.complete_workflow.assert_awaited_once_with("wf-1")

    @staticmethod
    async def _passthrough_to_thread(fn, *args, **kwargs):
        """Run the function directly instead of in a thread for testing."""
        return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# 7. Clone Progress Handler Tests
# ---------------------------------------------------------------------------


class TestCloneProgressHandler:
    """Test the CloneProgressHandler that translates GitPython progress."""

    def test_handler_invokes_callback(self):
        import git

        from graph_kb_api.graph_kb.repositories.clone_progress import (
            CloneProgressHandler,
        )

        calls = []

        def callback(phase, current, total, message):
            calls.append((phase, current, total, message))

        handler = CloneProgressHandler(callback)

        # Simulate receiving_objects progress
        handler.update(
            git.RemoteProgress.RECEIVING,
            50,
            100,
            "receiving",
        )

        assert len(calls) == 1
        assert calls[0][0] == "receiving_objects"
        assert calls[0][1] == 50
        assert calls[0][2] == 100

    def test_handler_suppresses_callback_errors(self):
        import git

        from graph_kb_api.graph_kb.repositories.clone_progress import (
            CloneProgressHandler,
        )

        def bad_callback(phase, current, total, message):
            raise RuntimeError("Callback error!")

        handler = CloneProgressHandler(bad_callback)

        # Should not raise
        handler.update(git.RemoteProgress.RECEIVING, 50, 100, "test")

    def test_handler_maps_all_known_phases(self):

        from graph_kb_api.graph_kb.repositories.clone_progress import (
            _OP_CODE_STAGE_MAP,
            CloneProgressHandler,
        )

        calls = []

        def callback(phase, current, total, message):
            calls.append(phase)

        handler = CloneProgressHandler(callback)

        for op_code in _OP_CODE_STAGE_MAP:
            handler.update(op_code, 1, 10, "")

        # All known phases should be mapped
        assert len(calls) == len(_OP_CODE_STAGE_MAP)
        assert "receiving_objects" in calls
        assert "resolving_deltas" in calls


# ---------------------------------------------------------------------------
# 8. _handle_start Routing Tests
# ---------------------------------------------------------------------------


class TestHandleStartRouting:
    """Test that _handle_start correctly routes ingest messages."""

    @pytest.mark.asyncio
    async def test_handle_start_routes_ingest(self):
        """_handle_start should create IngestPayload and dispatch to handle_ingest_workflow."""
        from graph_kb_api.websocket.handlers import _handle_start

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)
        mock_manager.create_workflow.return_value = "wf-123"

        dispatched = []

        async def mock_handle_ingest(client_id, workflow_id, payload):
            dispatched.append((client_id, workflow_id, payload))

        payload = {
            "workflow_type": "ingest",
            "git_url": "https://github.com/owner/repo.git",
            "branch": "main",
        }

        with (
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch(
                "graph_kb_api.websocket.handlers.handle_ingest_workflow",
                mock_handle_ingest,
            ),
            patch("asyncio.create_task") as mock_create_task,
        ):
            await _handle_start("client-1", payload)

        # Verify workflow was created
        mock_manager.create_workflow.assert_called_once_with("client-1", "ingest")

        # Verify create_task was called (the handler is dispatched as a task)
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_start_invalid_payload_sends_error(self):
        """Invalid payload should send error event."""
        from graph_kb_api.websocket.handlers import _handle_start

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)

        # Missing workflow_type
        payload = {"git_url": "https://github.com/owner/repo.git"}

        with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
            await _handle_start("client-1", payload)

        # Should have sent an error
        mock_manager.send_event.assert_awaited()
        call_kwargs = mock_manager.send_event.call_args
        assert call_kwargs.kwargs.get("event_type") == "error" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "error"
        )
