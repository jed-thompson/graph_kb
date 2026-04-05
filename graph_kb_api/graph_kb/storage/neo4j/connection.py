"""Neo4j session and transaction management.

This module provides the SessionManager class for managing Neo4j driver sessions
and transactions with proper lifecycle management and connection pooling.
"""

from contextlib import contextmanager
from typing import Generator, Optional

from neo4j import Driver, GraphDatabase, Session, Transaction
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from graph_kb_api.graph_kb.config import Neo4jConfig
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ConnectionError(Exception):
    """Raised when connection to Neo4j fails."""

    pass


class TransactionError(Exception):
    """Raised when a transaction fails."""

    pass


class SessionManager:
    """Manages Neo4j driver sessions and transactions.

    This class provides:
    - Lazy initialization of the Neo4j driver with connection pooling
    - Context manager for session lifecycle (automatic cleanup)
    - Context manager for explicit transaction boundaries
    - Proper resource cleanup on close

    Example usage:
        ```python
        config = Neo4jConfig.from_env()
        session_manager = SessionManager(config)

        # Using session context manager
        with session_manager.session() as session:
            result = session.run("MATCH (n) RETURN count(n)")

        # Using transaction context manager for atomic operations
        with session_manager.transaction() as tx:
            tx.run("CREATE (n:Node {id: $id})", id="123")
            tx.run("CREATE (m:Node {id: $id})", id="456")
            # Commits automatically on success, rolls back on exception

        # Clean up when done
        session_manager.close()
        ```
    """

    def __init__(
        self,
        config: Neo4jConfig,
        max_pool_size: Optional[int] = None,
        connection_timeout: Optional[int] = None,
    ):
        """Initialize the SessionManager.

        Args:
            config: Neo4j connection configuration.
            max_pool_size: Maximum number of connections in the pool (uses config value if not provided).
            connection_timeout: Timeout in seconds for acquiring a connection (uses config value if not provided).
        """
        self._config = config
        self._max_pool_size = max_pool_size or config.max_pool_size
        self._connection_timeout = connection_timeout or config.connection_timeout
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        """Get or create the Neo4j driver with connection pooling.

        The driver is lazily initialized on first access and reused for
        subsequent calls. Connection pooling is configured based on the
        constructor parameters.

        Returns:
            The Neo4j driver instance.

        Raises:
            ConnectionError: If connection to Neo4j fails.
        """
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self._config.uri,
                    auth=(self._config.user, self._config.password),
                    max_connection_pool_size=self._max_pool_size,
                    connection_acquisition_timeout=self._connection_timeout,
                )
                logger.info(
                    f"Created Neo4j driver for {self._config.uri} "
                    f"(pool_size={self._max_pool_size})"
                )
            except ServiceUnavailable as e:
                logger.error(f"Failed to connect to Neo4j at {self._config.uri}: {e}")
                raise ConnectionError(
                    f"Failed to connect to Neo4j at {self._config.uri}: {e}"
                ) from e
        return self._driver

    @property
    def database(self) -> str:
        """Get the configured database name."""
        return self._config.database

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager for Neo4j session lifecycle.

        Provides automatic session cleanup when the context exits.
        Sessions are created from the connection pool and returned
        to the pool when done.

        Yields:
            A Neo4j Session instance.

        Raises:
            ConnectionError: If connection to Neo4j fails.

        Example:
            ```python
            with session_manager.session() as session:
                result = session.run("MATCH (n) RETURN n LIMIT 10")
                for record in result:
                    print(record)
            # Session is automatically closed here
            ```
        """
        session = None
        try:
            session = self.driver.session(database=self._config.database)
            yield session
        except ServiceUnavailable as e:
            logger.error(f"Neo4j service unavailable: {e}")
            raise ConnectionError(f"Neo4j service unavailable: {e}") from e
        finally:
            if session is not None:
                session.close()

    @contextmanager
    def transaction(self) -> Generator[Transaction, None, None]:
        """Context manager for explicit transaction boundaries.

        Provides atomic operations with automatic commit on success
        and rollback on failure. Use this when you need multiple
        operations to succeed or fail together.

        Yields:
            A Neo4j Transaction instance.

        Raises:
            ConnectionError: If connection to Neo4j fails.
            TransactionError: If the transaction fails and is rolled back.

        Example:
            ```python
            with session_manager.transaction() as tx:
                tx.run("CREATE (a:Node {id: $id})", id="1")
                tx.run("CREATE (b:Node {id: $id})", id="2")
                tx.run("MATCH (a {id: '1'}), (b {id: '2'}) CREATE (a)-[:LINKS]->(b)")
            # All operations commit together, or all roll back on error
            ```
        """
        session = None
        tx = None
        try:
            session = self.driver.session(database=self._config.database)
            tx = session.begin_transaction()
            yield tx
            tx.commit()
            logger.debug("Transaction committed successfully")
        except ServiceUnavailable as e:
            logger.error(f"Neo4j service unavailable during transaction: {e}")
            if tx is not None:
                try:
                    tx.rollback()
                    logger.debug("Transaction rolled back due to service unavailable")
                except Exception:
                    pass  # Rollback may fail if connection is lost
            raise ConnectionError(f"Neo4j service unavailable: {e}") from e
        except Neo4jError as e:
            logger.error(f"Transaction failed: {e}")
            if tx is not None:
                try:
                    tx.rollback()
                    logger.debug("Transaction rolled back due to Neo4j error")
                except Exception:
                    pass  # Rollback may fail
            raise TransactionError(f"Transaction failed: {e}") from e
        except Exception as e:
            logger.error(f"Transaction failed with unexpected error: {e}")
            if tx is not None:
                try:
                    tx.rollback()
                    logger.debug("Transaction rolled back due to unexpected error")
                except Exception:
                    pass  # Rollback may fail
            raise TransactionError(f"Transaction failed: {e}") from e
        finally:
            if session is not None:
                session.close()

    def close(self) -> None:
        """Close the Neo4j driver and release all resources.

        This method should be called when the SessionManager is no longer
        needed to properly release connection pool resources.

        After calling close(), the SessionManager can still be used - a new
        driver will be created on the next session/transaction request.
        """
        if self._driver is not None:
            try:
                self._driver.close()
                logger.debug("Neo4j driver closed")
            except Exception as e:
                logger.warning(f"Error closing Neo4j driver: {e}")
            finally:
                self._driver = None

    def health_check(self) -> bool:
        """Check if the Neo4j connection is healthy.

        Returns:
            True if the connection is healthy, False otherwise.
        """
        try:
            with self.session() as session:
                result = session.run("RETURN 1 as health")
                record = result.single()
                return record is not None and record["health"] == 1
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def __enter__(self) -> "SessionManager":
        """Support using SessionManager as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the driver when exiting the context."""
        self.close()
