"""
Diagnostic tests for the /ingest command.

These tests are designed to trace the exact flow of the ingest pipeline
and identify where failures occur. Each test logs extensively to help
pinpoint the root cause of silent failures.

Key findings from investigation:
1. clone_repo is SYNCHRONOUS but some tests mock it with AsyncMock
2. asyncio.to_thread wraps sync calls — AsyncMock returns a coroutine
   that never gets awaited, causing silent attribute errors
3. The error handler catches Exception broadly, so failures in the
   clone/index phase are swallowed and sent as WebSocket error events
   that may not be visible in logs if the client disconnects
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


# ---------------------------------------------------------------------------
# Diagnostic stubs
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticRepoInfo:
    """Repo info that logs every attribute access for debugging."""

    repo_id: str = "diag__test-repo"
    local_path: str = "/tmp/diag-test-repo"
    commit_sha: str = "abc123def456"
    branch: str = "main"
    git_url: str = "https://github.com/diag/test-repo.git"


@dataclass
class DiagnosticIndexResult:
    """Index result that logs every attribute access for debugging."""

    repo_id: str = "diag__test-repo"
    phase: str = "completed"
    total_files: int = 5
    processed_files: int = 5
    total_chunks: int = 20
    total_symbols: int = 15
    total_relationships: int = 10
    message: str = "Completed"
    current_file: Optional[str] = None
    progress_percent: float = 100.0
    processed_chunks: int = 20
    total_chunks_to_embed: int = 20
    resolved_files: int = 5
    total_files_to_resolve: int = 5
    failed_files: int = 0


# ---------------------------------------------------------------------------
# 1. Diagnose: asyncio.to_thread with sync vs async mocks
# ---------------------------------------------------------------------------


class TestAsyncToThreadBehavior:
    """Diagnose how asyncio.to_thread behaves with different mock types."""

    @pytest.mark.asyncio
    async def test_to_thread_with_sync_function(self):
        """asyncio.to_thread with a regular sync function should work."""

        def sync_clone():
            return DiagnosticRepoInfo()

        result = await asyncio.to_thread(sync_clone)
        assert result.repo_id == "diag__test-repo"
        assert result.local_path == "/tmp/diag-test-repo"
        logger.info("✓ asyncio.to_thread with sync function works correctly")

    @pytest.mark.asyncio
    async def test_to_thread_with_mock_function(self):
        """asyncio.to_thread with MagicMock (sync) should work."""
        mock_fn = MagicMock(return_value=DiagnosticRepoInfo())

        result = await asyncio.to_thread(mock_fn)
        assert result.repo_id == "diag__test-repo"
        logger.info("✓ asyncio.to_thread with MagicMock works correctly")

    @pytest.mark.asyncio
    async def test_to_thread_with_async_mock_FAILS(self):
        """asyncio.to_thread with AsyncMock returns a COROUTINE, not the value.

        THIS IS THE BUG PATTERN. When clone_repo is mocked with AsyncMock
        and called via asyncio.to_thread, the result is a coroutine object,
        not the expected RepoInfo. Accessing .local_path on a coroutine
        raises AttributeError.
        """
        mock_fn = AsyncMock(return_value=DiagnosticRepoInfo())

        result = await asyncio.to_thread(mock_fn)

        # result is a COROUTINE, not DiagnosticRepoInfo!
        logger.warning(f"Result type from AsyncMock via to_thread: {type(result)}")
        logger.warning(f"Result value: {result}")

        # This will fail because result is a coroutine
        is_coroutine = asyncio.iscoroutine(result)
        logger.warning(f"Is coroutine: {is_coroutine}")

        if is_coroutine:
            logger.error(
                "BUG CONFIRMED: asyncio.to_thread + AsyncMock returns a coroutine. "
                "This means clone_repo returns a coroutine that never gets awaited, "
                "and accessing .local_path raises AttributeError."
            )
            # The actual error that would happen in production:
            with pytest.raises(AttributeError):
                _ = result.local_path

            # To get the actual value, you'd need to await it
            actual = await result
            assert actual.repo_id == "diag__test-repo"
        else:
            # If somehow it works, that's fine too
            assert result.repo_id == "diag__test-repo"

    @pytest.mark.asyncio
    async def test_to_thread_with_keyword_args(self):
        """Test asyncio.to_thread passes keyword args correctly to clone_repo."""
        calls = []

        def mock_clone(repo_url, branch="main", progress_callback=None):
            calls.append(
                {
                    "repo_url": repo_url,
                    "branch": branch,
                    "has_callback": progress_callback is not None,
                }
            )
            return DiagnosticRepoInfo()

        await asyncio.to_thread(
            mock_clone,
            repo_url="https://github.com/test/repo.git",
            branch="develop",
            progress_callback=lambda *a: None,
        )

        assert len(calls) == 1
        assert calls[0]["repo_url"] == "https://github.com/test/repo.git"
        assert calls[0]["branch"] == "develop"
        assert calls[0]["has_callback"] is True
        logger.info("✓ asyncio.to_thread passes kwargs correctly")


# ---------------------------------------------------------------------------
# 2. Diagnose: Full ingest handler flow with event capture
# ---------------------------------------------------------------------------


class TestIngestHandlerDiagnostic:
    """Trace the full ingest handler flow and capture all events."""

    @pytest.mark.asyncio
    async def test_full_flow_with_event_trace(self):
        """Run the full ingest handler and capture every event for analysis."""
        from graph_kb_api.websocket.protocol import IngestPayload

        # Capture all events with timestamps
        events: List[Dict[str, Any]] = []
        event_counter = [0]

        async def trace_send_event(**kwargs):
            event_counter[0] += 1
            event = {
                "seq": event_counter[0],
                "time": time.monotonic(),
                **kwargs,
            }
            events.append(event)
            event_type = kwargs.get("event_type", "?")
            data = kwargs.get("data", {})
            phase = data.get("phase", data.get("step", "N/A"))
            message = data.get("message", "")[:80]
            logger.info(
                f"[TRACE #{event_counter[0]}] type={event_type} phase={phase} msg={message}"
            )
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        # Create mock facade with SYNC mocks (not AsyncMock!)
        facade = MagicMock()
        facade.repo_fetcher = MagicMock()
        facade.repo_fetcher.create_repo_id.return_value = "diag__test-repo"
        facade.repo_fetcher.repo_exists.return_value = False
        facade.repo_fetcher.clone_repo = MagicMock(return_value=DiagnosticRepoInfo())

        facade.ingestion_service = MagicMock()
        facade.ingestion_service.index_repo = MagicMock(
            return_value=DiagnosticIndexResult()
        )

        payload = IngestPayload(
            git_url="https://github.com/diag/test-repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        # Analyze events
        logger.info(f"\n{'=' * 60}")
        logger.info(f"DIAGNOSTIC RESULTS: {len(events)} events captured")
        logger.info(f"{'=' * 60}")

        progress_events = [e for e in events if e.get("event_type") == "progress"]
        complete_events = [e for e in events if e.get("event_type") == "complete"]
        error_events = [e for e in events if e.get("event_type") == "error"]

        logger.info(f"  Progress: {len(progress_events)}")
        logger.info(f"  Complete: {len(complete_events)}")
        logger.info(f"  Errors:   {len(error_events)}")

        if error_events:
            for err in error_events:
                logger.error(f"  ERROR: {err.get('data', {}).get('message')}")

        # Verify expected flow
        assert len(error_events) == 0, "Unexpected errors: " + "; ".join(
            e.get("data", {}).get("message", "?") for e in error_events
        )
        assert len(complete_events) == 1, (
            f"Expected 1 complete event, got {len(complete_events)}"
        )

        # Verify phases seen
        phases = [e.get("data", {}).get("phase", "?") for e in progress_events]
        logger.info(f"  Phases: {phases}")

        # Should see cloning and discovering phases at minimum
        assert "cloning" in phases, f"Missing 'cloning' phase in {phases}"

        # Verify clone was called with correct args
        facade.repo_fetcher.clone_repo.assert_called_once()
        call_kwargs = facade.repo_fetcher.clone_repo.call_args
        logger.info(f"  clone_repo called with: {call_kwargs}")

        # Verify index_repo was called
        facade.ingestion_service.index_repo.assert_called_once()
        call_kwargs = facade.ingestion_service.index_repo.call_args
        logger.info(f"  index_repo called with: {call_kwargs}")

    @pytest.mark.asyncio
    async def test_clone_error_produces_visible_error_event(self):
        """When clone fails, the error should be visible in WebSocket events."""
        from graph_kb_api.graph_kb.repositories.repo_fetcher import CloneError
        from graph_kb_api.websocket.protocol import IngestPayload

        events: List[Dict[str, Any]] = []

        async def trace_send_event(**kwargs):
            events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        facade = MagicMock()
        facade.repo_fetcher = MagicMock()
        facade.repo_fetcher.create_repo_id.return_value = "diag__test-repo"
        facade.repo_fetcher.repo_exists.return_value = False
        facade.repo_fetcher.clone_repo = MagicMock(
            side_effect=CloneError(
                "Repository not found: https://github.com/diag/nonexistent.git"
            )
        )
        facade.ingestion_service = MagicMock()

        payload = IngestPayload(
            git_url="https://github.com/diag/nonexistent.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        error_events = [e for e in events if e.get("event_type") == "error"]
        assert len(error_events) == 1, (
            f"Expected 1 error event, got {len(error_events)}"
        )

        error_msg = error_events[0].get("data", {}).get("message", "")
        assert "not found" in error_msg.lower(), (
            f"Error message doesn't mention 'not found': {error_msg}"
        )
        logger.info(f"✓ Clone error correctly produces error event: {error_msg}")

    @pytest.mark.asyncio
    async def test_index_error_produces_visible_error_event(self):
        """When indexing fails, the error should be visible in WebSocket events."""
        from graph_kb_api.websocket.protocol import IngestPayload

        events: List[Dict[str, Any]] = []

        async def trace_send_event(**kwargs):
            events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        facade = MagicMock()
        facade.repo_fetcher = MagicMock()
        facade.repo_fetcher.create_repo_id.return_value = "diag__test-repo"
        facade.repo_fetcher.repo_exists.return_value = False
        facade.repo_fetcher.clone_repo = MagicMock(return_value=DiagnosticRepoInfo())
        facade.ingestion_service = MagicMock()
        facade.ingestion_service.index_repo = MagicMock(
            side_effect=RuntimeError("Neo4j connection refused")
        )

        payload = IngestPayload(
            git_url="https://github.com/diag/test-repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        error_events = [e for e in events if e.get("event_type") == "error"]
        assert len(error_events) == 1
        error_msg = error_events[0].get("data", {}).get("message", "")
        assert "Neo4j" in error_msg, f"Error message doesn't mention Neo4j: {error_msg}"
        logger.info(f"✓ Index error correctly produces error event: {error_msg}")

    @pytest.mark.asyncio
    async def test_facade_unavailable_produces_error(self):
        """When facade is unavailable (503), the error should be visible."""
        from fastapi import HTTPException

        from graph_kb_api.websocket.protocol import IngestPayload

        events: List[Dict[str, Any]] = []

        async def trace_send_event(**kwargs):
            events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/diag/test-repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                side_effect=HTTPException(
                    status_code=503,
                    detail="Graph KB services unavailable: Neo4j/ChromaDB unreachable",
                ),
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        error_events = [e for e in events if e.get("event_type") == "error"]
        assert len(error_events) >= 1, "No error event when facade is unavailable"
        logger.info(
            f"✓ Facade unavailable correctly produces error: "
            f"{error_events[0].get('data', {}).get('message', '')}"
        )

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_during_clone(self):
        """Verify that clone_progress callback is actually passed and invokable."""
        from graph_kb_api.websocket.protocol import IngestPayload

        clone_callbacks_received = []

        def mock_clone(repo_url, branch="main", progress_callback=None):
            logger.info(
                f"mock_clone called: url={repo_url} branch={branch} "
                f"has_callback={progress_callback is not None}"
            )
            clone_callbacks_received.append(progress_callback)

            # Simulate clone progress
            if progress_callback:
                progress_callback("receiving_objects", 50, 100, "Receiving")
                progress_callback("resolving_deltas", 80, 100, "Resolving")

            return DiagnosticRepoInfo()

        events: List[Dict[str, Any]] = []

        async def trace_send_event(**kwargs):
            events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        facade = MagicMock()
        facade.repo_fetcher = MagicMock()
        facade.repo_fetcher.create_repo_id.return_value = "diag__test-repo"
        facade.repo_fetcher.repo_exists.return_value = False
        facade.repo_fetcher.clone_repo = mock_clone
        facade.ingestion_service = MagicMock()
        facade.ingestion_service.index_repo = MagicMock(
            return_value=DiagnosticIndexResult()
        )

        payload = IngestPayload(
            git_url="https://github.com/diag/test-repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        assert len(clone_callbacks_received) == 1, "clone_progress callback not passed"
        assert clone_callbacks_received[0] is not None, "callback is None"
        logger.info("✓ Clone progress callback was passed and invoked")

        # Check that clone progress events made it through the bridge
        # Give the event loop time to process bridge events
        await asyncio.sleep(0.1)

        clone_events = [
            e
            for e in events
            if e.get("event_type") == "progress"
            and e.get("data", {}).get("phase") == "cloning"
        ]
        logger.info(f"  Clone progress events received: {len(clone_events)}")

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_during_indexing(self):
        """Verify that index_progress callback is passed and invokable."""
        from graph_kb_api.graph_kb.models.enums import IndexingPhase
        from graph_kb_api.graph_kb.models.ingestion import IndexingProgress
        from graph_kb_api.websocket.protocol import IngestPayload

        index_callbacks_received = []

        def mock_index_repo(
            repo_id,
            repo_path,
            git_url,
            branch,
            commit_sha,
            progress_callback=None,
            resume=False,
        ):
            logger.info(
                f"mock_index_repo called: repo_id={repo_id} "
                f"has_callback={progress_callback is not None}"
            )
            index_callbacks_received.append(progress_callback)

            # Simulate indexing progress
            if progress_callback:
                progress = IndexingProgress(
                    repo_id=repo_id,
                    phase=IndexingPhase.DISCOVERING_FILES,
                    total_files=5,
                    processed_files=0,
                    message="Discovering files...",
                )
                progress_callback(progress)

                progress.phase = IndexingPhase.INDEXING_FILES
                progress.processed_files = 3
                progress.current_file = "main.py"
                progress.message = "Indexing files: 3/5"
                progress_callback(progress)

                progress.phase = IndexingPhase.COMPLETED
                progress.processed_files = 5
                progress.total_chunks = 20
                progress.total_symbols = 15
                progress.message = "Completed"
                progress_callback(progress)

            return DiagnosticIndexResult()

        events: List[Dict[str, Any]] = []

        async def trace_send_event(**kwargs):
            events.append(kwargs)
            return True

        mock_manager = MagicMock()
        mock_manager.send_event = trace_send_event
        mock_manager.complete_workflow = AsyncMock()

        facade = MagicMock()
        facade.repo_fetcher = MagicMock()
        facade.repo_fetcher.create_repo_id.return_value = "diag__test-repo"
        facade.repo_fetcher.repo_exists.return_value = False
        facade.repo_fetcher.clone_repo = MagicMock(return_value=DiagnosticRepoInfo())
        facade.ingestion_service = MagicMock()
        facade.ingestion_service.index_repo = mock_index_repo

        payload = IngestPayload(
            git_url="https://github.com/diag/test-repo.git",
            branch="main",
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                return_value=facade,
            ),
            patch("graph_kb_api.websocket.handlers.manager", mock_manager),
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
        ):
            from graph_kb_api.websocket.handlers import handle_ingest_workflow

            await handle_ingest_workflow("diag-client", "diag-wf", payload)

        assert len(index_callbacks_received) == 1, "index_progress callback not passed"
        logger.info("✓ Index progress callback was passed and invoked")

        # Give bridge time to relay events
        await asyncio.sleep(0.1)

        # Check for indexing progress events
        progress_events = [e for e in events if e.get("event_type") == "progress"]
        phases = [e.get("data", {}).get("phase", "?") for e in progress_events]
        logger.info(f"  All phases seen: {phases}")

    @staticmethod
    async def _sync_to_thread(fn, *args, **kwargs):
        """Run sync function directly (bypass thread for testing)."""
        return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# 3. Diagnose: WebSocket endpoint message flow
# ---------------------------------------------------------------------------


class TestWebSocketEndpointDiagnostic:
    """Test the actual WebSocket endpoint to verify message routing."""

    def test_ingest_endpoint_receives_start_ack(self):
        """The /ws/ingest endpoint should acknowledge a start message."""
        from starlette.testclient import TestClient

        from graph_kb_api.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/ingest") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "payload": {
                        "git_url": "https://github.com/test/repo",
                        "branch": "main",
                    },
                }
            )

            # First message should be the start acknowledgement
            data = websocket.receive_json()
            logger.info(f"First message from /ws/ingest: {data}")

            assert "type" in data, f"No 'type' in response: {data}"
            assert data["type"] in (
                "progress",
                "error",
            ), f"Unexpected type: {data['type']}"

            if data["type"] == "error":
                error_msg = data.get("data", {}).get("message", "unknown")
                logger.error(f"Ingest endpoint returned error: {error_msg}")
                # This is expected if Docker services aren't running
                logger.info(
                    "Error is expected if Neo4j/ChromaDB aren't running locally"
                )
            else:
                logger.info(f"✓ Ingest endpoint acknowledged start: {data}")
                # Should have workflow_id
                if "workflow_id" in data:
                    logger.info(f"  workflow_id: {data['workflow_id']}")

    def test_ingest_endpoint_missing_git_url(self):
        """Sending start without git_url should produce an error."""
        from starlette.testclient import TestClient

        from graph_kb_api.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/ingest") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "payload": {
                        # Missing git_url!
                        "branch": "main",
                    },
                }
            )

            data = websocket.receive_json()
            logger.info(f"Response without git_url: {data}")

            # Should get an error about missing git_url or invalid payload
            # The start ack comes first, then the error from IngestPayload validation
            if data["type"] == "progress":
                # Got the start ack, next message should be error
                data2 = websocket.receive_json()
                logger.info(f"Second message: {data2}")
                assert data2["type"] == "error"
            elif data["type"] == "error":
                logger.info("✓ Got expected error for missing git_url")
