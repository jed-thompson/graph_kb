"""
Integration tests for the ingest workflow via WebSocket.

Tests the full flow from WebSocket message to progress events and completion.
Designed to diagnose the silent failure issue in /ingest workflows.
"""

from dataclasses import dataclass
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from graph_kb_api.websocket.handlers import handle_ingest_workflow
from graph_kb_api.websocket.manager import ConnectionManager
from graph_kb_api.websocket.protocol import IngestPayload


@dataclass
class MockRepoInfo:
    """Mock repo info for testing."""
    repo_id: str
    local_path: str
    commit_sha: str
    branch: str
    git_url: str


@dataclass
class MockIndexingResult:
    """Mock indexing result for testing."""
    repo_id: str
    total_files: int
    total_chunks: int
    total_symbols: int
    total_relationships: int


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self.closed = False

    async def send_json(self, data: Dict[str, Any]) -> None:
        self.sent_messages.append(data)


class MockRepoFetcher:
    """Mock repo fetcher for testing."""

    def __init__(self, repo_info: MockRepoInfo):
        self._repo_info = repo_info
        self._existing_repos: set = set()

    def create_repo_id(self, git_url: str) -> str:
        return "test_owner_test-repo"

    def repo_exists(self, repo_id: str) -> bool:
        return repo_id in self._existing_repos

    def set_repo_exists(self, exists: bool) -> None:
        if exists:
            self._existing_repos.add(self._repo_info.repo_id)
        else:
            self._existing_repos.discard(self._repo_info.repo_id)

    def clone_repo(
        self,
        repo_url: str,
        branch: str = "main",
        progress_callback=None,
        **kwargs
    ) -> MockRepoInfo:
        # Simulate progress callbacks
        if progress_callback:
            progress_callback("counting_objects", 0, 100, "Counting")
            progress_callback("receiving_objects", 50, 100, "Receiving")
            progress_callback("checking_out", 100, 100, "Checkout")
        return self._repo_info

    def update_repo(self, repo_id: str, branch: str = "main", **kwargs) -> MockRepoInfo:
        return self._repo_info


class MockIngestionService:
    """Mock ingestion service for testing."""

    def __init__(self, result: MockIndexingResult):
        self._result = result
        self._pause_requested = False

    def index_repo(
        self,
        repo_id: str,
        repo_path: str,
        git_url: str,
        branch: str,
        commit_sha: str,
        progress_callback=None,
        resume: bool = False,
    ) -> MockIndexingResult:
        from graph_kb_api.graph_kb.models.enums import IndexingPhase
        from graph_kb_api.graph_kb.models.ingestion import IndexingProgress

        # Simulate progress callbacks through different phases
        if progress_callback:
            # Initializing phase
            progress = IndexingProgress(
                repo_id=repo_id,
                phase=IndexingPhase.INITIALIZING,
                message="Initializing...",
            )
            progress_callback(progress)

            # Discovering files
            progress = IndexingProgress(
                repo_id=repo_id,
                phase=IndexingPhase.DISCOVERING_FILES,
                total_files=10,
                message="Discovering files...",
            )
            progress_callback(progress)

            # Indexing files
            for i in range(1, 11):
                progress = IndexingProgress(
                    repo_id=repo_id,
                    phase=IndexingPhase.INDEXING_FILES,
                    total_files=10,
                    processed_files=i,
                    current_file=f"file_{i}.py",
                    message=f"Indexing file_{i}.py",
                )
                progress_callback(progress)

            # Generating embeddings
            progress = IndexingProgress(
                repo_id=repo_id,
                phase=IndexingPhase.GENERATING_EMBEDDINGS,
                total_chunks=50,
                processed_chunks=50,
                message="Embeddings complete",
            )
            progress_callback(progress)

            # Finalizing
            progress = IndexingProgress(
                repo_id=repo_id,
                phase=IndexingPhase.FINALIZING,
                message="Finalizing...",
            )
            progress_callback(progress)

        return self._result

    def request_pause(self) -> None:
        self._pause_requested = True

    def clear_pause(self) -> None:
        self._pause_requested = False

    def is_pause_requested(self) -> bool:
        return self._pause_requested


class MockFacade:
    """Mock facade for testing."""

    def __init__(self, repo_fetcher: MockRepoFetcher, ingestion_service: MockIngestionService):
        self.repo_fetcher = repo_fetcher
        self.ingestion_service = ingestion_service


def create_mock_manager():
    """Create a mock manager with event tracking."""
    manager = ConnectionManager()
    sent_events: List[Dict[str, Any]] = []

    async def mock_send_event(**kwargs):
        sent_events.append(kwargs)
        return True

    manager.send_event = mock_send_event
    return manager, sent_events


class TestIngestWorkflowIntegration:
    """Integration tests for ingest workflow."""

    @pytest.fixture
    def mock_repo_info(self):
        """Create mock repo info."""
        return MockRepoInfo(
            repo_id="test_owner_test-repo",
            local_path="/tmp/repos/test_owner_test-repo/latest",
            commit_sha="abcd1234567890",
            branch="main",
            git_url="https://github.com/test_owner/test-repo.git",
        )

    @pytest.fixture
    def mock_indexing_result(self):
        """Create mock indexing result."""
        return MockIndexingResult(
            repo_id="test_owner_test-repo",
            total_files=10,
            total_chunks=50,
            total_symbols=100,
            total_relationships=25,
        )

    @pytest.mark.asyncio
    async def test_ingest_workflow_sends_progress_events(
        self, mock_repo_info, mock_indexing_result
    ):
        """Test that ingest workflow sends progress events through the flow."""
        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        # Create mock manager with event tracking
        mock_manager, sent_events = create_mock_manager()

        # Setup mocks
        repo_fetcher = MockRepoFetcher(mock_repo_info)
        ingestion_service = MockIngestionService(mock_indexing_result)
        facade = MockFacade(repo_fetcher, ingestion_service)

        with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
            with patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade", return_value=facade
            ):
                await handle_ingest_workflow(client_id, workflow_id, payload)

        # Verify progress events were sent
        progress_events = [e for e in sent_events if e.get("event_type") == "progress"]
        complete_events = [e for e in sent_events if e.get("event_type") == "complete"]
        error_events = [e for e in sent_events if e.get("event_type") == "error"]

        # Should have multiple progress events
        assert len(progress_events) >= 3, f"Expected >= 3 progress events, got {len(progress_events)}"

        # Should have one complete event
        assert len(complete_events) == 1, f"Expected 1 complete event, got {len(complete_events)}"

        # Should have no error events
        assert len(error_events) == 0, f"Expected 0 error events, got {len(error_events)}"

        # Verify complete event has stats
        complete_data = complete_events[0]["data"]
        assert "stats" in complete_data
        assert complete_data["stats"]["total_files"] == 10

    @pytest.mark.asyncio
    async def test_ingest_workflow_handles_clone_error(
        self, mock_repo_info, mock_indexing_result
    ):
        """Test that ingest workflow handles clone errors gracefully."""
        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        mock_manager, sent_events = create_mock_manager()

        # Setup mock that raises on clone
        repo_fetcher = MockRepoFetcher(mock_repo_info)

        def failing_clone(*args, **kwargs):
            raise Exception("Clone failed: repository not found")

        repo_fetcher.clone_repo = failing_clone

        ingestion_service = MockIngestionService(mock_indexing_result)
        facade = MockFacade(repo_fetcher, ingestion_service)

        with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
            with patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade", return_value=facade
            ):
                await handle_ingest_workflow(client_id, workflow_id, payload)

        # Verify error event was sent
        error_events = [e for e in sent_events if e.get("event_type") == "error"]
        assert len(error_events) == 1
        assert "Clone failed" in error_events[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_ingest_workflow_handles_indexing_error(
        self, mock_repo_info, mock_indexing_result
    ):
        """Test that ingest workflow handles indexing errors gracefully."""
        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        mock_manager, sent_events = create_mock_manager()

        # Setup mocks
        repo_fetcher = MockRepoFetcher(mock_repo_info)

        def failing_index(*args, **kwargs):
            raise Exception("Indexing failed: database connection error")

        ingestion_service = MockIngestionService(mock_indexing_result)
        ingestion_service.index_repo = failing_index
        facade = MockFacade(repo_fetcher, ingestion_service)

        with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
            with patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade", return_value=facade
            ):
                await handle_ingest_workflow(client_id, workflow_id, payload)

        # Verify error event was sent
        error_events = [e for e in sent_events if e.get("event_type") == "error"]
        assert len(error_events) == 1
        assert "Indexing failed" in error_events[0]["data"]["message"]

    @pytest.mark.asyncio
    async def test_ingest_workflow_progress_phases(
        self, mock_repo_info, mock_indexing_result
    ):
        """Test that ingest workflow goes through expected phases."""
        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        mock_manager, sent_events = create_mock_manager()

        repo_fetcher = MockRepoFetcher(mock_repo_info)
        ingestion_service = MockIngestionService(mock_indexing_result)
        facade = MockFacade(repo_fetcher, ingestion_service)

        with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
            with patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade", return_value=facade
            ):
                await handle_ingest_workflow(client_id, workflow_id, payload)

        # Extract phases from progress events
        progress_events = [e for e in sent_events if e.get("event_type") == "progress"]
        phases = [e["data"].get("phase") for e in progress_events]

        # Verify expected phases are present
        assert "cloning" in phases, f"Expected 'cloning' phase in {phases}"
        assert "discovering" in phases, f"Expected 'discovering' phase in {phases}"

    @pytest.mark.asyncio
    async def test_ingest_workflow_bridge_stats_logged(
        self, mock_repo_info, mock_indexing_result, caplog
    ):
        """Test that bridge stats are logged at workflow teardown."""
        import logging

        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        mock_manager, _ = create_mock_manager()

        repo_fetcher = MockRepoFetcher(mock_repo_info)
        ingestion_service = MockIngestionService(mock_indexing_result)
        facade = MockFacade(repo_fetcher, ingestion_service)

        with caplog.at_level(logging.INFO):
            with patch("graph_kb_api.websocket.handlers.manager", mock_manager):
                with patch(
                    "graph_kb_api.websocket.handlers.get_graph_kb_facade", return_value=facade
                ):
                    await handle_ingest_workflow(client_id, workflow_id, payload)

        # Check for bridge stats in logs
        log_messages = [r.message for r in caplog.records]
        stats_logged = any("bridge_stats" in msg for msg in log_messages)
        assert stats_logged, f"Expected 'bridge_stats' in logs: {log_messages}"


class TestIngestWorkflowWithDockerServices:
    """
    Integration tests that require Docker services.

    These tests connect to actual Docker services but mock only the
    slow/expensive parts (actual git clone, actual indexing).
    """

    @pytest.fixture
    def mock_repo_info(self):
        """Create mock repo info."""
        return MockRepoInfo(
            repo_id="test_owner_test-repo",
            local_path="/tmp/repos/test_owner_test-repo/latest",
            commit_sha="abcd1234567890",
            branch="main",
            git_url="https://github.com/test_owner/test-repo.git",
        )

    @pytest.fixture
    def mock_indexing_result(self):
        """Create mock indexing result."""
        return MockIndexingResult(
            repo_id="test_owner_test-repo",
            total_files=10,
            total_chunks=50,
            total_symbols=100,
            total_relationships=25,
        )

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires running Docker services - run manually")
    async def test_ingest_with_real_facade(
        self, mock_repo_info, mock_indexing_result
    ):
        """
        Test ingest workflow with real facade (requires Docker).

        This test connects to actual Neo4j/ChromaDB services but mocks
        the clone and index operations for speed.
        """
        from graph_kb_api.dependencies import get_graph_kb_facade
        from graph_kb_api.websocket.manager import manager

        client_id = "test-client"
        workflow_id = "test-workflow"
        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        sent_events: List[Dict[str, Any]] = []

        async def mock_send_event(**kwargs):
            sent_events.append(kwargs)
            print(f"Event: {kwargs.get('event_type')} - {kwargs.get('data', {}).get('phase', 'N/A')}")
            return True

        # Use the global manager but with our mock send_event
        original_send = manager.send_event
        manager.send_event = mock_send_event

        try:
            # Get real facade
            facade = get_graph_kb_facade()

            if not facade.ingestion_service:
                pytest.skip("Ingestion service not available")

            if not facade.repo_fetcher:
                pytest.skip("Repo fetcher not available")

            # Replace with mocks for speed
            original_clone = facade.repo_fetcher.clone_repo
            original_index = facade.ingestion_service.index_repo

            facade.repo_fetcher.clone_repo = MockRepoFetcher(mock_repo_info).clone_repo
            facade.ingestion_service.index_repo = MockIngestionService(mock_indexing_result).index_repo

            try:
                await handle_ingest_workflow(client_id, workflow_id, payload)
            finally:
                facade.repo_fetcher.clone_repo = original_clone
                facade.ingestion_service.index_repo = original_index

            # Verify events were sent
            progress_events = [e for e in sent_events if e.get("event_type") == "progress"]
            complete_events = [e for e in sent_events if e.get("event_type") == "complete"]

            print(f"\nProgress events: {len(progress_events)}")
            print(f"Complete events: {len(complete_events)}")

            assert len(progress_events) > 0, "No progress events sent"
            assert len(complete_events) == 1, f"Expected 1 complete event, got {len(complete_events)}"

        finally:
            manager.send_event = original_send


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
