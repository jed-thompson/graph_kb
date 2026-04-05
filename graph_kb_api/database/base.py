"""Database base configuration and session management.

This module provides:
- Async engine setup for PostgreSQL
- Declarative base for ORM models
- Session factory for dependency injection
- Database initialization functions
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import exc as sql_exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from graph_kb_api.config import settings
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


# Declarative base for all ORM models
class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class DatabaseError(Exception):
    """Base exception for database-related errors."""

    def __init__(self, message: str, original: Exception | None = None):
        self.message = message
        self.original = original
        super().__init__(message)


def get_database_url() -> str:
    """Get database URL from environment variables.

    Returns:
        The PostgreSQL connection URL.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
    """

    return settings.require_database_url()


def get_pool_config() -> dict:
    """Get connection pool configuration from environment variables.

    Returns:
        Dictionary with pool_size and max_overflow.
    """
    return {
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
    }


# Global async engine (initialized once)
_async_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create async database engine.

    The engine is created once and reused for application lifetime.

    Returns:
        The async SQLAlchemy engine.
    """
    global _async_engine
    global _async_session_maker

    if _async_engine is None:
        database_url = get_database_url()
        pool_config = get_pool_config()

        logger.info(f"Creating async PostgreSQL engine: {database_url[:30]}...")
        logger.debug(f"Pool config: {pool_config}")

        _async_engine = create_async_engine(
            database_url,
            echo=False,  # Set to True for SQL query logging
            pool_size=pool_config["pool_size"],
            max_overflow=pool_config["max_overflow"],
            pool_pre_ping=True,  # Test connections before using
        )

        # Create session factory
        _async_session_maker = async_sessionmaker(
            bind=_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("PostgreSQL engine and session factory created")

    return _async_engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Return the global session factory, creating the engine if needed."""
    get_engine()  # ensure engine + session maker are initialised
    if _async_session_maker is None:
        raise DatabaseError("Database engine not initialized.")
    return _async_session_maker


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session for use in async context.

    This is a primary dependency for FastAPI endpoints.

    Usage:
        ```python
        async with get_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
        ```

    Yields:
        An async SQLAlchemy session.

    Raises:
        DatabaseError: If engine is not initialized.
    """
    global _async_session_maker

    if _async_session_maker is None:
        raise DatabaseError(
            "Database engine not initialized. "
            "Call get_engine() before using get_session()."
        )

    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except sql_exc.SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise DatabaseError(f"Database operation failed: {e}", original=e) from e


async def init_database() -> None:
    """Initialize database engine and create missing tables.

    Call this during application startup to ensure that engine
    is created and ready for use.

    Raises:
        DatabaseError: If engine initialization fails.
    """
    try:
        engine = get_engine()
        # Test connection
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        # Create any missing tables (safe no-op for existing ones)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully (tables synced)")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise DatabaseError(f"Database initialization failed: {e}", original=e) from e


async def close_database() -> None:
    """Close database engine and dispose of connections.

    Call this during application shutdown.

    Raises:
        DatabaseError: If engine is not initialized.
    """
    global _async_engine

    if _async_engine is not None:
        logger.info("Closing database connections...")
        await _async_engine.dispose()
        _async_engine = None
        _async_session_maker = None
        logger.info("Database connections closed")



@asynccontextmanager
async def get_db_session_ctx() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions.

    Unlike ``get_session`` (which is an async *generator* designed for
    FastAPI's ``Depends``), this is a proper ``async with`` context
    manager that can be used anywhere — including WebSocket handlers
    and background tasks.

    Usage::

        async with get_db_session_ctx() as session:
            result = await session.execute(select(User))
    """
    maker = get_session_maker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except sql_exc.SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise DatabaseError(f"Database operation failed: {e}", original=e) from e
