"""
Checkpointer configuration for LangGraph v3 workflows.

This module provides a factory for creating checkpointers based on environment
configuration, supporting MemorySaver for development and AsyncPostgresSaver
for production use.
"""

import logging
import os
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class CheckpointerFactory:
    """
    Factory for creating LangGraph checkpointers based on environment configuration.

    Supports two checkpointer types:
    - MemorySaver: In-memory checkpointing for development/testing
    - AsyncPostgresSaver: PostgreSQL-based checkpointing for production deployments

    Configuration is controlled via environment variables:
    - LANGGRAPH_CHECKPOINTER_TYPE: "memory" or "postgres"
    - LANGGRAPH_POSTGRES_URI or DATABASE_URL: PostgreSQL connection URI

    The factory uses an explicit init/close async lifecycle to manage connection pools
    cleanly across the FastAPI application lifespan.
    """

    _instance: Optional[object] = None
    _pool: Optional[AsyncConnectionPool] = None
    _checkpointer_type: Optional[str] = None

    @classmethod
    async def init_checkpointer(cls):
        """
        Async initialization for the checkpointer pool (if postgres) and table setup.
        Must be called during the application startup lifespan.
        """
        checkpointer_type = os.getenv("LANGGRAPH_CHECKPOINTER_TYPE", "memory").lower()

        if checkpointer_type == "postgres":
            postgres_uri: str | None = os.getenv("LANGGRAPH_POSTGRES_URI") or os.getenv("DATABASE_URL")
            if not postgres_uri:
                raise ValueError(
                    "DATABASE_URL or LANGGRAPH_POSTGRES_URI environment variable required for postgres checkpointer"
                )

            # Strip any accidental wrapping quotes (e.g. from Docker/env files)
            postgres_uri = postgres_uri.strip("\"'")

            # Rewrite asyncpg URI for psycopg (which LangGraph uses natively)
            # psycopg pool expects standard postgresql:// not postgresql+psycopg://
            if postgres_uri.startswith("postgresql+asyncpg://"):
                postgres_uri = postgres_uri.replace("postgresql+asyncpg://", "postgresql://")
            elif postgres_uri.startswith("postgresql+psycopg://"):
                postgres_uri = postgres_uri.replace("postgresql+psycopg://", "postgresql://")

            logger.info("Initializing Postgres checkpointer connection pool")
            try:
                cls._pool = AsyncConnectionPool(
                    conninfo=postgres_uri,
                    max_size=20,
                    kwargs={"autocommit": True},
                )
                await cls._pool.open()
            except Exception as e:
                logger.error(f"Failed to open Postgres checkpointer pool: {e}")
                raise

            saver = AsyncPostgresSaver(cls._pool)
            logger.info("Running Postgres checkpointer setup (migrations)")
            await saver.setup()
            cls._instance = saver
            cls._checkpointer_type = "postgres"
        else:
            logger.info("Initializing Memory checkpointer")
            cls._instance = MemorySaver()
            cls._checkpointer_type = "memory"

    @classmethod
    async def close_checkpointer(cls):
        """Close connection pools if active. Must be called during shutdown lifespan."""
        if cls._pool:
            logger.info("Closing Postgres checkpointer connection pool")
            await cls._pool.close()
            cls._pool = None
        cls._instance = None
        cls._checkpointer_type = None

    @staticmethod
    def create_checkpointer():
        """
        Return the singleton checkpointer instance.
        If init_checkpointer() was not called (e.g. in tests), it attempts a memory fallback.
        """
        if CheckpointerFactory._instance is None:
            checkpointer_type = os.getenv("LANGGRAPH_CHECKPOINTER_TYPE", "memory").lower()
            if checkpointer_type == "memory":
                logger.debug("Falling back to synchronous MemorySaver initialization (testing only)")
                CheckpointerFactory._instance = MemorySaver()
                CheckpointerFactory._checkpointer_type = "memory"
            else:
                raise RuntimeError(
                    "CheckpointerFactory.init_checkpointer() must be called before using the Checkpointer for postgres"
                )
        return CheckpointerFactory._instance

    @staticmethod
    def get_checkpointer_info() -> dict:
        """
        Get information about the configured checkpointer.

        Returns:
            Dictionary with checkpointer type and configuration details
        """
        # Always read from env, even if we forced it in test setup
        checkpointer_type: str = os.getenv("LANGGRAPH_CHECKPOINTER_TYPE", "memory").lower()

        info = {"type": checkpointer_type, "configured": True}

        if checkpointer_type == "postgres":
            postgres_uri: str = os.getenv("LANGGRAPH_POSTGRES_URI") or os.getenv("DATABASE_URL", "")
            if postgres_uri and "@" in postgres_uri:
                parts: list[str] = postgres_uri.split("@")
                if ":" in parts[0]:
                    user_pass: list[str] = parts[0].split(":")
                    masked_uri = f"{user_pass[0]}:****@{parts[1]}"
                    info["uri"] = masked_uri
                else:
                    info["uri"] = "configured"
            else:
                info["uri"] = "not_set"

        return info
