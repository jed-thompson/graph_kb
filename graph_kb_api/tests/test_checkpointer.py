"""
Unit tests for CheckpointerFactory.

Validates the factory pattern, singleton behaviour, type validation,
and info reporting for the LangGraph checkpointer configuration.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton state before each test."""
    CheckpointerFactory._instance = None
    CheckpointerFactory._checkpointer_type = None
    CheckpointerFactory._pool = None
    yield
    CheckpointerFactory._instance = None
    CheckpointerFactory._checkpointer_type = None
    CheckpointerFactory._pool = None


@pytest.mark.asyncio
class TestCheckpointerFactoryMemory:
    """Memory checkpointer creation."""

    @patch.dict("os.environ", {"LANGGRAPH_CHECKPOINTER_TYPE": "memory"}, clear=False)
    @patch("graph_kb_api.flows.v3.checkpointer.MEMORY_AVAILABLE", True)
    @patch("graph_kb_api.flows.v3.checkpointer.MemorySaver")
    async def test_init_creates_memory_saver(self, MockMemorySaver):
        mock_instance = AsyncMock()
        MockMemorySaver.return_value = mock_instance

        await CheckpointerFactory.init_checkpointer()
        result = CheckpointerFactory.create_checkpointer()

        assert result is mock_instance
        MockMemorySaver.assert_called_once()

    @patch.dict("os.environ", {}, clear=False)
    @patch("graph_kb_api.flows.v3.checkpointer.MEMORY_AVAILABLE", True)
    @patch("graph_kb_api.flows.v3.checkpointer.MemorySaver")
    async def test_defaults_to_memory_when_env_unset(self, MockMemorySaver):
        if "LANGGRAPH_CHECKPOINTER_TYPE" in os.environ:
            del os.environ["LANGGRAPH_CHECKPOINTER_TYPE"]

        mock_instance = AsyncMock()
        MockMemorySaver.return_value = mock_instance

        await CheckpointerFactory.init_checkpointer()
        result = CheckpointerFactory.create_checkpointer()

        assert result is mock_instance

    @patch.dict("os.environ", {"LANGGRAPH_CHECKPOINTER_TYPE": "memory"}, clear=False)
    @patch("graph_kb_api.flows.v3.checkpointer.MEMORY_AVAILABLE", False)
    async def test_memory_raises_when_unavailable(self):
        with pytest.raises(ValueError, match="MemorySaver not available"):
            await CheckpointerFactory.init_checkpointer()

    @patch.dict("os.environ", {"LANGGRAPH_CHECKPOINTER_TYPE": "memory"}, clear=False)
    @patch("graph_kb_api.flows.v3.checkpointer.MEMORY_AVAILABLE", True)
    @patch("graph_kb_api.flows.v3.checkpointer.MemorySaver")
    def test_create_checkpointer_fallback(self, MockMemorySaver):
        # Even without calling init_checkpointer, if memory is requested it falls back
        mock_instance = AsyncMock()
        MockMemorySaver.return_value = mock_instance

        result = CheckpointerFactory.create_checkpointer()
        assert result is mock_instance


@pytest.mark.asyncio
class TestCheckpointerFactoryPostgres:
    """Postgres checkpointer creation."""

    @patch.dict(
        "os.environ",
        {
            "LANGGRAPH_CHECKPOINTER_TYPE": "postgres",
            "LANGGRAPH_POSTGRES_URI": "postgresql+asyncpg://user:pass@localhost/db",
        },
        clear=False,
    )
    @patch("graph_kb_api.flows.v3.checkpointer.POSTGRES_AVAILABLE", True)
    @patch("graph_kb_api.flows.v3.checkpointer.AsyncPostgresSaver")
    @patch("graph_kb_api.flows.v3.checkpointer.AsyncConnectionPool")
    async def test_postgres_init_creates_saver(self, MockPool, MockPostgresSaver):
        mock_pool = AsyncMock()
        MockPool.return_value = mock_pool
        mock_instance = AsyncMock()
        MockPostgresSaver.return_value = mock_instance

        await CheckpointerFactory.init_checkpointer()
        result = CheckpointerFactory.create_checkpointer()

        assert result is mock_instance
        # Should rewrite asyncpg URI to psycopg
        MockPool.assert_called_once_with(
            conninfo="postgresql+psycopg://user:pass@localhost/db", max_size=20, kwargs={"autocommit": True}
        )
        mock_pool.open.assert_awaited_once()
        mock_instance.setup.assert_awaited_once()

    @patch.dict(
        "os.environ",
        {"LANGGRAPH_CHECKPOINTER_TYPE": "postgres"},
        clear=False,
    )
    @patch("graph_kb_api.flows.v3.checkpointer.POSTGRES_AVAILABLE", True)
    async def test_postgres_raises_without_uri(self):
        if "LANGGRAPH_POSTGRES_URI" in os.environ:
            del os.environ["LANGGRAPH_POSTGRES_URI"]

        with pytest.raises(ValueError, match="LANGGRAPH_POSTGRES_URI"):
            await CheckpointerFactory.init_checkpointer()

    @patch.dict(
        "os.environ",
        {
            "LANGGRAPH_CHECKPOINTER_TYPE": "postgres",
            "LANGGRAPH_POSTGRES_URI": "postgresql://user:pass@localhost/db",
        },
        clear=False,
    )
    @patch("graph_kb_api.flows.v3.checkpointer.POSTGRES_AVAILABLE", False)
    async def test_postgres_raises_when_unavailable(self):
        with pytest.raises(ValueError, match="AsyncPostgresSaver not available"):
            await CheckpointerFactory.init_checkpointer()

    @patch.dict(
        "os.environ",
        {
            "LANGGRAPH_CHECKPOINTER_TYPE": "postgres",
            "LANGGRAPH_POSTGRES_URI": "postgresql://user:pass@localhost/db",
        },
        clear=False,
    )
    def test_postgres_raises_if_init_not_called(self):
        with pytest.raises(RuntimeError, match="must be called before"):
            CheckpointerFactory.create_checkpointer()


class TestCheckpointerFactoryValidation:
    """Invalid type handling."""

    @patch.dict("os.environ", {"LANGGRAPH_CHECKPOINTER_TYPE": "sqlite"}, clear=False)
    def test_rejects_invalid_type_on_create(self):
        # create_checkpointer raises RuntimeError if init was not called for unknown type
        with pytest.raises(RuntimeError, match="must be called before"):
            CheckpointerFactory.create_checkpointer()


class TestCheckpointerInfo:
    """get_checkpointer_info reporting."""

    @patch.dict("os.environ", {"LANGGRAPH_CHECKPOINTER_TYPE": "memory"}, clear=False)
    def test_memory_info(self):
        info = CheckpointerFactory.get_checkpointer_info()
        assert info["type"] == "memory"
        assert info["configured"] is True
        assert "uri" not in info

    @patch.dict(
        "os.environ",
        {
            "LANGGRAPH_CHECKPOINTER_TYPE": "postgres",
            "LANGGRAPH_POSTGRES_URI": "postgresql://admin:secret@db.host:5432/mydb",
        },
        clear=False,
    )
    def test_postgres_info_masks_password(self):
        info = CheckpointerFactory.get_checkpointer_info()
        assert info["type"] == "postgres"
        assert "secret" not in info["uri"]
        assert "****" in info["uri"]
        assert "db.host" in info["uri"]

    @patch.dict(
        "os.environ",
        {"LANGGRAPH_CHECKPOINTER_TYPE": "postgres"},
        clear=False,
    )
    def test_postgres_info_no_uri(self):
        if "LANGGRAPH_POSTGRES_URI" in os.environ:
            del os.environ["LANGGRAPH_POSTGRES_URI"]
        info = CheckpointerFactory.get_checkpointer_info()
        assert info["uri"] == "not_set"

    def test_defaults_to_memory_info(self):
        if "LANGGRAPH_CHECKPOINTER_TYPE" in os.environ:
            del os.environ["LANGGRAPH_CHECKPOINTER_TYPE"]
        info = CheckpointerFactory.get_checkpointer_info()
        assert info["type"] == "memory"
