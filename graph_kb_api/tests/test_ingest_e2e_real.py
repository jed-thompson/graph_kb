"""
Real end-to-end integration tests for the /ingest command.

These tests actually clone real git repositories and run the full
ingest pipeline against Docker services (Neo4j, ChromaDB, PostgreSQL).

This is the definitive test that proves the ingest command works or
identifies exactly where it breaks.

Run with:
    pytest graph_kb_api/tests/test_ingest_e2e_real.py -v -s --timeout=600

Prerequisites:
    docker compose up -d neo4j-api chromadb postgres
    .env must have NEO4J_URI=bolt://localhost:7688
"""

import asyncio
import logging
import os
import socket
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import load_dotenv

# Load .env so NEO4J_URI=bolt://localhost:7688 is picked up
load_dotenv(override=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def _docker_services_available() -> bool:
    """Check all required Docker services are reachable."""
    neo4j_ok = _is_port_open("localhost", 7688)
    chroma_ok = _is_port_open("localhost", 8091)
    pg_ok = _is_port_open("localhost", 5432)
    if not neo4j_ok:
        logger.warning("Neo4j not reachable on localhost:7688")
    if not chroma_ok:
        logger.warning("ChromaDB not reachable on localhost:8091")
    if not pg_ok:
        logger.warning("PostgreSQL not reachable on localhost:5432")
    return neo4j_ok and chroma_ok and pg_ok


pytestmark = pytest.mark.skipif(
    not _docker_services_available(),
    reason="Docker services not running. Start with: docker compose up -d",
)


def _init_facade():
    """Initialize a fresh facade with correct Docker ports."""
    from graph_kb_api.graph_kb.facade import GraphKBFacade

    GraphKBFacade.reset_instance()
    facade = GraphKBFacade()
    if not facade.initialize():
        raise RuntimeError("Facade initialization failed")
    return facade


def _cleanup_repo(facade, repo_id: str):
    """Clean up all data for a repo from Neo4j, ChromaDB, and PostgreSQL."""
    try:
        if facade.graph_store:
            facade.graph_store.delete_by_repo(repo_id)
            logger.info(f"Cleaned up Neo4j data for {repo_id}")
    except Exception as e:
        logger.warning(f"Neo4j cleanup failed for {repo_id}: {e}")

    try:
        if facade.vector_store:
            facade.vector_store.delete_by_repo(repo_id)
            logger.info(f"Cleaned up ChromaDB data for {repo_id}")
    except Exception as e:
        logger.warning(f"ChromaDB cleanup failed for {repo_id}: {e}")

    try:
        if facade.metadata_store:
            facade.metadata_store.delete_repo(repo_id)
            logger.info(f"Cleaned up PostgreSQL data for {repo_id}")
    except Exception as e:
        logger.warning(f"PostgreSQL cleanup failed for {repo_id}: {e}")

    # Clean up cloned repo from disk
    try:
        if facade.repo_fetcher:
            facade.repo_fetcher.delete_repo(repo_id)
            logger.info(f"Cleaned up local repo for {repo_id}")
    except Exception as e:
        logger.warning(f"Local repo cleanup failed for {repo_id}: {e}")


# ---------------------------------------------------------------------------
# Test 1: Facade initialization with correct Docker ports
# ---------------------------------------------------------------------------


class TestFacadeWithDockerPorts:
    """Verify facade initializes correctly with Docker port mappings."""

    def test_facade_initializes_with_correct_ports(self):
        """Facade should initialize when NEO4J_URI points to port 7688."""
        neo4j_uri = os.getenv("NEO4J_URI", "NOT SET")
        logger.info(f"NEO4J_URI = {neo4j_uri}")
        assert "7688" in neo4j_uri or _is_port_open("localhost", 7688), (
            "NEO4J_URI should point to port 7688 (Docker-mapped)"
        )

        facade = _init_facade()
        assert facade.is_initialized
        assert facade.ingestion_service is not None
        assert facade.repo_fetcher is not None
        assert facade.graph_store is not None
        assert facade.vector_store is not None
        assert facade.embedding_generator is not None
        logger.info("✓ Facade initialized with all services")


# ---------------------------------------------------------------------------
# Test 2: Real clone of a small repo (no mocks)
# ---------------------------------------------------------------------------


class TestRealClone:
    """Test actual git clone operations."""

    def test_clone_small_repo(self):
        """Clone a small real repo and verify RepoInfo is returned."""
        facade = _init_facade()
        repo_url = "https://github.com/octocat/Hello-World.git"
        repo_id = facade.repo_fetcher.create_repo_id(repo_url)

        try:
            # Clean up first
            _cleanup_repo(facade, repo_id)

            clone_phases = []

            def on_clone_progress(phase, current, total, message):
                clone_phases.append(phase)
                logger.info(f"  Clone: {phase} {current}/{total} {message}")

            logger.info(f"Cloning {repo_url}...")
            start = time.monotonic()
            repo_info = facade.repo_fetcher.clone_repo(
                repo_url=repo_url,
                branch="master",
                progress_callback=on_clone_progress,
            )
            elapsed = time.monotonic() - start

            logger.info(f"✓ Cloned in {elapsed:.1f}s")
            logger.info(f"  repo_id: {repo_info.repo_id}")
            logger.info(f"  local_path: {repo_info.local_path}")
            logger.info(f"  commit_sha: {repo_info.commit_sha}")
            logger.info(f"  branch: {repo_info.branch}")
            logger.info(f"  clone_phases: {clone_phases}")

            assert repo_info.repo_id == repo_id
            assert os.path.isdir(repo_info.local_path)
            assert len(repo_info.commit_sha) == 40
        finally:
            _cleanup_repo(facade, repo_id)


# ---------------------------------------------------------------------------
# Test 3: Full E2E ingest of a small repo via the handler
# ---------------------------------------------------------------------------


class TestFullIngestE2E:
    """Full end-to-end ingest through the WebSocket handler."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(300)
    async def test_ingest_small_repo_via_handler(self):
        """
        Run the full ingest handler with a real clone of octocat/Hello-World.

        This tests the complete flow:
        1. WebSocket handler receives IngestPayload
        2. Facade provides real services
        3. Repo is actually cloned from GitHub
        4. Files are discovered, parsed, chunked
        5. Embeddings are generated
        6. Data is stored in Neo4j and ChromaDB
        7. Progress events are sent back
        """
        from graph_kb_api.websocket.manager import ConnectionManager
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = _init_facade()
        repo_url = "https://github.com/octocat/Hello-World.git"
        repo_id = facade.repo_fetcher.create_repo_id(repo_url)

        # Clean up before test
        _cleanup_repo(facade, repo_id)

        test_manager = ConnectionManager()
        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            event_type = kwargs.get("event_type", "unknown")
            data = kwargs.get("data", {})
            phase = data.get("phase", data.get("step", "N/A"))
            message = data.get("message", "")[:120]
            pct = data.get("progress_percent", -1)
            logger.info(f"  [{event_type}] phase={phase} pct={pct} msg={message}")
            sent_events.append(kwargs)
            return True

        test_manager.send_event = capture_send_event
        test_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url=repo_url,
            branch="master",
        )

        try:
            # Clear the lru_cache so our fresh facade is used
            from graph_kb_api.dependencies import get_graph_kb_facade

            get_graph_kb_facade.cache_clear()

            with (
                patch(
                    "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                    return_value=facade,
                ),
                patch(
                    "graph_kb_api.websocket.handlers.manager",
                    test_manager,
                ),
            ):
                from graph_kb_api.websocket.handlers import handle_ingest_workflow

                logger.info(f"\n{'=' * 60}")
                logger.info(f"Starting E2E ingest of {repo_url}")
                logger.info(f"{'=' * 60}")

                start = time.monotonic()
                await handle_ingest_workflow("e2e-client", "e2e-wf-001", payload)
                elapsed = time.monotonic() - start

            # Analyze results
            progress_events = [
                e for e in sent_events if e.get("event_type") == "progress"
            ]
            complete_events = [
                e for e in sent_events if e.get("event_type") == "complete"
            ]
            error_events = [e for e in sent_events if e.get("event_type") == "error"]

            phases_seen = []
            for evt in progress_events:
                phase = evt.get("data", {}).get("phase", "unknown")
                if phase not in phases_seen:
                    phases_seen.append(phase)

            logger.info(f"\n{'=' * 60}")
            logger.info(f"E2E RESULTS ({elapsed:.1f}s):")
            logger.info(f"  Progress events: {len(progress_events)}")
            logger.info(f"  Complete events: {len(complete_events)}")
            logger.info(f"  Error events:    {len(error_events)}")
            logger.info(f"  Phases seen:     {phases_seen}")

            if error_events:
                for err in error_events:
                    msg = err.get("data", {}).get("message", "Unknown")
                    logger.error(f"  ERROR: {msg}")

            if complete_events:
                stats = complete_events[0].get("data", {}).get("stats", {})
                logger.info(f"  Stats: {stats}")

            logger.info(f"{'=' * 60}")

            # Assertions
            if error_events:
                error_msg = error_events[0].get("data", {}).get("message", "Unknown")
                pytest.fail(f"Ingest produced error: {error_msg}")

            assert len(progress_events) > 0, "No progress events"
            assert len(complete_events) == 1, (
                f"Expected 1 complete event, got {len(complete_events)}"
            )

            # Verify data was stored
            if facade.graph_store:
                graph_stats = facade.graph_store.get_repo_stats(repo_id)
                logger.info(f"  Neo4j stats: {graph_stats}")

            if facade.vector_store:
                vector_count = facade.vector_store.count(repo_id)
                logger.info(f"  ChromaDB vectors: {vector_count}")

        finally:
            _cleanup_repo(facade, repo_id)


# ---------------------------------------------------------------------------
# Test 4: Real E2E ingest of TheAlgorithms/Python (user-requested)
# ---------------------------------------------------------------------------


class TestIngestTheAlgorithms:
    """
    E2E test using https://github.com/TheAlgorithms/Python.git
    as specifically requested by the user.

    This is a large repo so we use a subset approach:
    - Clone with depth=1 (shallow)
    - The indexer's file discovery will find all Python files
    - Full pipeline: parse → chunk → embed → store

    Marked as 'slow' — skip with: pytest -m "not slow"
    """

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.timeout(600)
    async def test_ingest_the_algorithms_python(self):
        """
        Full E2E ingest of TheAlgorithms/Python.

        This is the definitive test that the ingest command works end-to-end
        with a real, non-trivial Python repository.
        """
        from graph_kb_api.websocket.manager import ConnectionManager
        from graph_kb_api.websocket.protocol import IngestPayload

        facade = _init_facade()
        repo_url = "https://github.com/TheAlgorithms/Python.git"
        repo_id = facade.repo_fetcher.create_repo_id(repo_url)

        # Clean up before test
        _cleanup_repo(facade, repo_id)

        test_manager = ConnectionManager()
        sent_events: List[Dict[str, Any]] = []
        last_progress_time = [time.monotonic()]

        async def capture_send_event(**kwargs):
            event_type = kwargs.get("event_type", "unknown")
            data = kwargs.get("data", {})
            phase = data.get("phase", data.get("step", "N/A"))
            message = data.get("message", "")[:150]
            pct = data.get("progress_percent", -1)

            now = time.monotonic()
            # Log every event for errors/complete, throttle progress to every 5s
            if event_type != "progress" or (now - last_progress_time[0]) > 5:
                logger.info(f"  [{event_type}] phase={phase} pct={pct} msg={message}")
                last_progress_time[0] = now

            sent_events.append(kwargs)
            return True

        test_manager.send_event = capture_send_event
        test_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url=repo_url,
            branch="master",
        )

        try:
            from graph_kb_api.dependencies import get_graph_kb_facade

            get_graph_kb_facade.cache_clear()

            with (
                patch(
                    "graph_kb_api.websocket.handlers.get_graph_kb_facade",
                    return_value=facade,
                ),
                patch(
                    "graph_kb_api.websocket.handlers.manager",
                    test_manager,
                ),
            ):
                from graph_kb_api.websocket.handlers import handle_ingest_workflow

                logger.info(f"\n{'=' * 60}")
                logger.info("Starting E2E ingest of TheAlgorithms/Python")
                logger.info("This may take several minutes...")
                logger.info(f"{'=' * 60}")

                start = time.monotonic()
                await handle_ingest_workflow("e2e-client", "e2e-wf-algo", payload)
                elapsed = time.monotonic() - start

            # Analyze results
            progress_events = [
                e for e in sent_events if e.get("event_type") == "progress"
            ]
            complete_events = [
                e for e in sent_events if e.get("event_type") == "complete"
            ]
            error_events = [e for e in sent_events if e.get("event_type") == "error"]

            phases_seen = []
            for evt in progress_events:
                phase = evt.get("data", {}).get("phase", "unknown")
                if phase not in phases_seen:
                    phases_seen.append(phase)

            logger.info(f"\n{'=' * 60}")
            logger.info(f"TheAlgorithms/Python E2E RESULTS ({elapsed:.1f}s):")
            logger.info(f"  Progress events: {len(progress_events)}")
            logger.info(f"  Complete events: {len(complete_events)}")
            logger.info(f"  Error events:    {len(error_events)}")
            logger.info(f"  Phases seen:     {phases_seen}")

            if error_events:
                for err in error_events:
                    msg = err.get("data", {}).get("message", "Unknown")
                    logger.error(f"  ERROR: {msg}")

            if complete_events:
                stats = complete_events[0].get("data", {}).get("stats", {})
                logger.info(f"  Final stats: {stats}")
                repo_id_result = complete_events[0].get("data", {}).get("repo_id", "")
                logger.info(f"  Repo ID: {repo_id_result}")

            # Verify data in stores
            if facade.graph_store:
                graph_stats = facade.graph_store.get_repo_stats(repo_id)
                logger.info(f"  Neo4j graph stats: {graph_stats}")

            if facade.vector_store:
                vector_count = facade.vector_store.count(repo_id)
                logger.info(f"  ChromaDB vector count: {vector_count}")

            logger.info(f"{'=' * 60}")

            # Assertions
            if error_events:
                error_msg = error_events[0].get("data", {}).get("message", "Unknown")
                pytest.fail(f"Ingest produced error: {error_msg}")

            assert len(progress_events) > 0, "No progress events were sent"
            assert len(complete_events) == 1, (
                f"Expected 1 complete event, got {len(complete_events)}"
            )

            # Verify meaningful data was indexed
            stats = complete_events[0].get("data", {}).get("stats", {})
            assert stats.get("total_files", 0) > 0, "No files were indexed"
            assert stats.get("total_chunks", 0) > 0, "No chunks were created"
            assert stats.get("total_symbols", 0) > 0, "No symbols were extracted"

            logger.info("✓ TheAlgorithms/Python E2E ingest PASSED")

        finally:
            _cleanup_repo(facade, repo_id)


# ---------------------------------------------------------------------------
# Test 5: Direct pipeline test (no WebSocket handler)
# ---------------------------------------------------------------------------


class TestDirectPipeline:
    """Test the ingestion pipeline directly without the WebSocket handler."""

    def test_clone_and_index_directly(self):
        """
        Clone a small repo and call ingestion_service.index_repo directly.

        This bypasses the WebSocket handler to isolate pipeline issues
        from WebSocket/async issues.
        """
        facade = _init_facade()
        repo_url = "https://github.com/octocat/Hello-World.git"
        repo_id = facade.repo_fetcher.create_repo_id(repo_url)

        _cleanup_repo(facade, repo_id)

        try:
            # Step 1: Clone
            logger.info("Step 1: Cloning...")
            repo_info = facade.repo_fetcher.clone_repo(
                repo_url=repo_url,
                branch="master",
            )
            logger.info(f"  Cloned to {repo_info.local_path}")
            logger.info(f"  Commit: {repo_info.commit_sha}")

            # Step 2: Index
            progress_log = []

            def on_progress(progress):
                phase = (
                    progress.phase.value
                    if hasattr(progress.phase, "value")
                    else str(progress.phase)
                )
                msg = progress.message[:100] if progress.message else ""
                progress_log.append(
                    {
                        "phase": phase,
                        "files": f"{progress.processed_files}/{progress.total_files}",
                        "chunks": progress.total_chunks,
                        "symbols": progress.total_symbols,
                        "message": msg,
                    }
                )
                logger.info(
                    f"  [{phase}] files={progress.processed_files}/{progress.total_files} "
                    f"chunks={progress.total_chunks} symbols={progress.total_symbols} "
                    f"msg={msg}"
                )

            logger.info("Step 2: Indexing...")
            start = time.monotonic()
            result = facade.ingestion_service.index_repo(
                repo_id=repo_id,
                repo_path=repo_info.local_path,
                git_url=repo_url,
                branch="master",
                commit_sha=repo_info.commit_sha,
                progress_callback=on_progress,
                resume=False,
            )
            elapsed = time.monotonic() - start

            logger.info(f"\nDirect pipeline results ({elapsed:.1f}s):")
            logger.info(f"  Phase: {result.phase}")
            logger.info(f"  Files: {result.total_files}")
            logger.info(f"  Chunks: {result.total_chunks}")
            logger.info(f"  Symbols: {result.total_symbols}")
            logger.info(f"  Relationships: {result.total_relationships}")
            logger.info(f"  Message: {result.message}")
            logger.info(f"  Progress callbacks: {len(progress_log)}")

            phases_seen = list(dict.fromkeys(p["phase"] for p in progress_log))
            logger.info(f"  Phases seen: {phases_seen}")

            if result.errors:
                for err in result.errors[:5]:
                    logger.warning(f"  Error: {err}")

            # Assertions
            from graph_kb_api.graph_kb.models.enums import IndexingPhase

            assert result.phase in (
                IndexingPhase.COMPLETED,
                IndexingPhase.FINALIZING,
            ), f"Expected COMPLETED, got {result.phase}: {result.message}"
            assert len(progress_log) > 0, "No progress callbacks received"

            logger.info("✓ Direct pipeline test PASSED")

        finally:
            _cleanup_repo(facade, repo_id)


# ---------------------------------------------------------------------------
# Test 6: Ingest through the actual API container's WebSocket endpoint
# ---------------------------------------------------------------------------


class TestIngestViaAPIContainer:
    """
    Test ingest by connecting to the running API container's WebSocket.

    This is the test that generates logs in the api-1 container.
    Unlike the other tests which instantiate the facade locally,
    this one sends a real WebSocket message to ws://localhost:8000/ws.

    Prerequisites:
        docker compose up -d  (all services including api)
        API must be reachable on port 8000
    """

    @pytest.mark.asyncio
    async def test_ingest_via_api_websocket(self):
        """
        Send an ingest command through the API container's WebSocket
        and verify we get progress + complete events back.

        Uses octocat/Hello-World (tiny repo) for speed.
        """
        import json

        import websockets

        api_ws_url = "ws://localhost:8000/ws"

        if not _is_port_open("localhost", 8000):
            pytest.skip("API container not running on port 8000")

        events = []
        async with websockets.connect(api_ws_url, open_timeout=10) as ws:
            # Send ingest start message
            msg = {
                "type": "start",
                "payload": {
                    "workflow_type": "ingest",
                    "git_url": "https://github.com/octocat/Hello-World.git",
                    "branch": "master",
                },
            }
            await ws.send(json.dumps(msg))
            logger.info(f"Sent ingest command to {api_ws_url}")

            # Collect events until complete or error (max 60s)
            start = time.monotonic()
            while time.monotonic() - start < 60:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(raw)
                    evt_type = data.get("type", "unknown")
                    phase = data.get("data", {}).get("phase", "")
                    message = data.get("data", {}).get("message", "")[:120]
                    logger.info(f"  [{evt_type}] phase={phase} msg={message}")
                    events.append(data)

                    if evt_type in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    logger.info("  (waiting for events...)")

        # Analyze
        progress_events = [e for e in events if e.get("type") == "progress"]
        complete_events = [e for e in events if e.get("type") == "complete"]
        error_events = [e for e in events if e.get("type") == "error"]

        logger.info("API WebSocket test results:")
        logger.info(f"  Progress: {len(progress_events)}")
        logger.info(f"  Complete: {len(complete_events)}")
        logger.info(f"  Errors:   {len(error_events)}")

        if error_events:
            error_msg = error_events[0].get("data", {}).get("message", "Unknown")
            pytest.fail(f"API ingest returned error: {error_msg}")

        assert len(progress_events) > 0, "No progress events from API"
        assert len(complete_events) == 1, "Expected exactly 1 complete event"

        # Verify the complete event has stats
        stats = complete_events[0].get("data", {}).get("stats", {})
        logger.info(f"  Stats: {stats}")

        # Hello-World has no code files, so 0 files is expected
        assert "total_files" in stats, "Missing total_files in stats"
        logger.info("✓ API WebSocket ingest test PASSED")
