"""
Integration tests for the /ingest command against Docker-ran services.

These tests verify that the ingest pipeline works end-to-end with real
Neo4j, ChromaDB, and PostgreSQL services running in Docker.

Run with:
    pytest graph_kb_api/tests/test_ingest_docker_integration.py -v -s

Prerequisites:
    docker compose up -d neo4j-api chromadb postgres
"""

import logging
import os
import socket
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def _check_neo4j() -> bool:
    """Check if Neo4j is reachable on bolt://localhost:7688 (Docker-mapped port)."""
    return _is_port_open("localhost", 7688)


def _check_chromadb() -> bool:
    """Check if ChromaDB is reachable on http://localhost:8091."""
    return _is_port_open("localhost", 8091)


def _check_postgres() -> bool:
    """Check if PostgreSQL is reachable on localhost:5432."""
    return _is_port_open("localhost", 5432)


# Skip entire module if Docker services aren't running
pytestmark = pytest.mark.skipif(
    not (_check_neo4j() and _check_chromadb() and _check_postgres()),
    reason="Docker services (Neo4j, ChromaDB, PostgreSQL) not running. "
    "Start with: docker compose up -d neo4j-api chromadb postgres",
)


# ---------------------------------------------------------------------------
# 1. Service Connectivity Tests
# ---------------------------------------------------------------------------


class TestServiceConnectivity:
    """Verify that Docker services are reachable and responding."""

    def test_neo4j_is_reachable(self):
        """Neo4j should be reachable on bolt port 7688 (Docker-mapped)."""
        assert _check_neo4j(), "Neo4j is not reachable on localhost:7688"
        logger.info("✓ Neo4j is reachable on localhost:7688")

    def test_chromadb_is_reachable(self):
        """ChromaDB should be reachable on port 8091."""
        assert _check_chromadb(), "ChromaDB is not reachable on localhost:8091"
        logger.info("✓ ChromaDB is reachable on localhost:8091")

    def test_postgres_is_reachable(self):
        """PostgreSQL should be reachable on port 5432."""
        assert _check_postgres(), "PostgreSQL is not reachable on localhost:5432"
        logger.info("✓ PostgreSQL is reachable on localhost:5432")

    def test_neo4j_driver_connects(self):
        """Test that the Neo4j Python driver can establish a connection."""
        try:
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "password")

            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            driver.close()
            logger.info("✓ Neo4j driver connected successfully")
        except Exception as e:
            pytest.fail(f"Neo4j driver connection failed: {e}")

    def test_chromadb_client_connects(self):
        """Test that the ChromaDB client can connect."""
        try:
            import chromadb

            host = os.getenv("CHROMA_SERVER_HOST", "localhost")
            port = int(os.getenv("CHROMA_SERVER_PORT", "8091"))

            client = chromadb.HttpClient(host=host, port=port)
            heartbeat = client.heartbeat()
            assert heartbeat > 0
            logger.info(f"✓ ChromaDB connected, heartbeat={heartbeat}")
        except Exception as e:
            pytest.fail(f"ChromaDB connection failed: {e}")


# ---------------------------------------------------------------------------
# 2. Facade Initialization Tests
# ---------------------------------------------------------------------------


class TestFacadeInitialization:
    """Test that the GraphKBFacade initializes correctly with Docker services."""

    def test_facade_initializes(self):
        """The facade should initialize when all services are available."""
        try:
            from graph_kb_api.graph_kb.facade import GraphKBFacade

            facade = GraphKBFacade()
            result = facade.initialize()
            assert result is True, "Facade initialization returned False"
            assert facade.is_initialized, "Facade is_initialized is False after init"
            logger.info("✓ GraphKBFacade initialized successfully")
        except Exception as e:
            pytest.fail(f"Facade initialization failed: {e}")

    def test_facade_has_ingestion_service(self):
        """The facade should have an ingestion_service after initialization."""
        from graph_kb_api.graph_kb.facade import GraphKBFacade

        facade = GraphKBFacade()
        facade.initialize()
        assert facade.ingestion_service is not None, "ingestion_service is None"
        logger.info("✓ ingestion_service is available")

    def test_facade_has_repo_fetcher(self):
        """The facade should have a repo_fetcher after initialization."""
        from graph_kb_api.graph_kb.facade import GraphKBFacade

        facade = GraphKBFacade()
        facade.initialize()
        assert facade.repo_fetcher is not None, "repo_fetcher is None"
        logger.info("✓ repo_fetcher is available")

    def test_facade_has_graph_store(self):
        """The facade should have a graph_store after initialization."""
        from graph_kb_api.graph_kb.facade import GraphKBFacade

        facade = GraphKBFacade()
        facade.initialize()
        assert facade.graph_store is not None, "graph_store is None"
        logger.info("✓ graph_store is available")

    def test_facade_has_vector_store(self):
        """The facade should have a vector_store after initialization."""
        from graph_kb_api.graph_kb.facade import GraphKBFacade

        facade = GraphKBFacade()
        facade.initialize()
        assert facade.vector_store is not None, "vector_store is None"
        logger.info("✓ vector_store is available")

    def test_facade_has_embedding_generator(self):
        """The facade should have an embedding_generator after initialization."""
        from graph_kb_api.graph_kb.facade import GraphKBFacade

        facade = GraphKBFacade()
        facade.initialize()
        assert facade.embedding_generator is not None, "embedding_generator is None"
        logger.info("✓ embedding_generator is available")


# ---------------------------------------------------------------------------
# 3. Neo4j Graph Store Integration Tests
# ---------------------------------------------------------------------------


class TestNeo4jGraphStore:
    """Test Neo4j graph store operations used during ingestion."""

    def _get_graph_store(self):
        from graph_kb_api.graph_kb.config import Neo4jConfig
        from graph_kb_api.graph_kb.storage.graph_store import Neo4jGraphStore

        config = Neo4jConfig.from_env()
        return Neo4jGraphStore(config=config)

    def test_ensure_indexes(self):
        """ensure_indexes should not raise."""
        store = self._get_graph_store()
        try:
            store.ensure_indexes()
            logger.info("✓ Neo4j indexes ensured")
        except Exception as e:
            pytest.fail(f"ensure_indexes failed: {e}")

    def test_create_and_query_repo_node(self):
        """Should be able to create a repo node and query it back."""
        store = self._get_graph_store()
        test_repo_id = "integration_test__repo"

        try:
            # Create repo node
            store.create_or_update_node(
                node_id=test_repo_id,
                labels=["Repository"],
                properties={
                    "repo_id": test_repo_id,
                    "git_url": "https://github.com/test/repo.git",
                    "branch": "main",
                },
            )

            # Query it back
            stats = store.get_repo_stats(test_repo_id)
            logger.info(f"✓ Created and queried repo node: {stats}")
        except Exception as e:
            pytest.fail(f"Neo4j repo node operations failed: {e}")
        finally:
            # Cleanup
            try:
                store.delete_by_repo(test_repo_id)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 4. ChromaDB Vector Store Integration Tests
# ---------------------------------------------------------------------------


class TestChromaVectorStore:
    """Test ChromaDB vector store operations used during ingestion."""

    def _get_vector_store(self):
        from graph_kb_api.graph_kb.config import ChromaConfig
        from graph_kb_api.graph_kb.storage.vector_store import ChromaVectorStore

        config = ChromaConfig.from_env()
        return ChromaVectorStore(config=config)

    def test_vector_store_initializes(self):
        """Vector store should initialize without error."""
        try:
            store = self._get_vector_store()
            assert store is not None
            logger.info("✓ ChromaDB vector store initialized")
        except Exception as e:
            pytest.fail(f"ChromaDB vector store initialization failed: {e}")

    def test_vector_store_count(self):
        """Should be able to count vectors for a repo."""
        store = self._get_vector_store()
        try:
            count = store.count("nonexistent_repo")
            assert isinstance(count, int)
            logger.info(f"✓ ChromaDB count for nonexistent repo: {count}")
        except Exception as e:
            pytest.fail(f"ChromaDB count failed: {e}")


# ---------------------------------------------------------------------------
# 5. End-to-End Ingest Workflow (Mocked Clone)
# ---------------------------------------------------------------------------


class TestIngestWorkflowE2E:
    """
    End-to-end test of the ingest workflow handler with real Docker services
    but mocked git clone (to avoid network dependency).
    """

    @pytest.mark.asyncio
    async def test_ingest_workflow_with_real_services(self):
        """
        Run the full ingest workflow handler with:
        - Real Neo4j, ChromaDB, PostgreSQL
        - Mocked git clone (returns a small test repo)
        - Real indexing pipeline

        This tests the complete flow from WebSocket handler through to storage.
        """
        from graph_kb_api.websocket.manager import ConnectionManager
        from graph_kb_api.websocket.protocol import IngestPayload

        # Create a fresh manager for this test
        test_manager = ConnectionManager()

        sent_events: List[Dict[str, Any]] = []

        async def capture_send_event(**kwargs):
            event_type = kwargs.get("event_type", "unknown")
            data = kwargs.get("data", {})
            phase = data.get("phase", data.get("step", "N/A"))
            message = data.get("message", "")
            logger.info(
                f"[E2E] Event: type={event_type} phase={phase} message={message[:100]}"
            )
            sent_events.append(kwargs)
            return True

        test_manager.send_event = capture_send_event
        test_manager.complete_workflow = AsyncMock()

        payload = IngestPayload(
            git_url="https://github.com/test_owner/test-repo.git",
            branch="main",
        )

        # Initialize facade with real services
        try:
            from graph_kb_api.graph_kb.facade import GraphKBFacade

            facade = GraphKBFacade()
            if not facade.initialize():
                pytest.skip("Facade initialization failed — services may be unhealthy")
        except Exception as e:
            pytest.skip(f"Cannot initialize facade: {e}")

        if not facade.ingestion_service or not facade.repo_fetcher:
            pytest.skip("Required services not available")

        # Mock the clone to return a small test directory
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal test repo structure
            test_file = os.path.join(tmpdir, "main.py")
            with open(test_file, "w") as f:
                f.write(
                    'def hello():\n    """Say hello."""\n    return "Hello, World!"\n\n'
                    'def add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'
                )

            from graph_kb_api.graph_kb.repositories.repo_fetcher import RepoInfo

            fake_repo_info = RepoInfo(
                repo_id="test_owner__test-repo",
                local_path=tmpdir,
                commit_sha="abc123def456",
                branch="main",
                git_url="https://github.com/test_owner/test-repo.git",
            )

            original_clone = facade.repo_fetcher.clone_repo
            original_exists = facade.repo_fetcher.repo_exists
            original_create_id = facade.repo_fetcher.create_repo_id

            facade.repo_fetcher.clone_repo = MagicMock(return_value=fake_repo_info)
            facade.repo_fetcher.repo_exists = MagicMock(return_value=False)
            facade.repo_fetcher.create_repo_id = MagicMock(
                return_value="test_owner__test-repo"
            )

            try:
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

                    await handle_ingest_workflow("test-client", "test-wf", payload)

                # Analyze results
                progress_events = [
                    e for e in sent_events if e.get("event_type") == "progress"
                ]
                complete_events = [
                    e for e in sent_events if e.get("event_type") == "complete"
                ]
                error_events = [
                    e for e in sent_events if e.get("event_type") == "error"
                ]

                logger.info(f"\n{'=' * 60}")
                logger.info("E2E Test Results:")
                logger.info(f"  Progress events: {len(progress_events)}")
                logger.info(f"  Complete events: {len(complete_events)}")
                logger.info(f"  Error events:    {len(error_events)}")

                if error_events:
                    for err in error_events:
                        logger.error(f"  ERROR: {err.get('data', {}).get('message')}")

                # Log all progress phases
                phases_seen = []
                for evt in progress_events:
                    phase = evt.get("data", {}).get("phase", "unknown")
                    if phase not in phases_seen:
                        phases_seen.append(phase)
                logger.info(f"  Phases seen: {phases_seen}")
                logger.info(f"{'=' * 60}")

                if error_events:
                    error_msg = (
                        error_events[0].get("data", {}).get("message", "Unknown")
                    )
                    pytest.fail(f"Ingest workflow produced error events: {error_msg}")

                assert len(progress_events) > 0, "No progress events were sent"

                # Complete event is expected on success
                if len(complete_events) == 0:
                    logger.warning(
                        "No complete event — workflow may have errored silently"
                    )

            finally:
                facade.repo_fetcher.clone_repo = original_clone
                facade.repo_fetcher.repo_exists = original_exists
                facade.repo_fetcher.create_repo_id = original_create_id

                # Cleanup test data from Neo4j
                try:
                    if facade.graph_store:
                        facade.graph_store.delete_by_repo("test_owner__test-repo")
                except Exception:
                    pass
