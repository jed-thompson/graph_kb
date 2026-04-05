"""Tests for graph_kb_api.dependencies module.

Validates the fixed get_db_session async generator and
the is_database_available helper.
"""

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from graph_kb_api.dependencies import get_db_session, is_database_available


class TestIsDatabaseAvailable:
    """Tests for the is_database_available helper."""

    def test_returns_bool(self) -> None:
        """is_database_available always returns a boolean."""
        result = is_database_available()
        assert isinstance(result, bool)

    def test_returns_false_when_get_session_is_none(self) -> None:
        """When the database module failed to import, returns False."""
        with patch("graph_kb_api.dependencies._get_session", None):
            assert is_database_available() is False

    def test_returns_false_when_session_maker_is_none(self) -> None:
        """When the session maker hasn't been initialised, returns False."""
        with (
            patch("graph_kb_api.dependencies._get_session", lambda: None),
            patch("graph_kb_api.database.base._async_session_maker", None),
        ):
            assert is_database_available() is False


class TestGetDbSessionSignature:
    """Tests for get_db_session function signature and structure."""

    def test_is_async_generator_function(self) -> None:
        """get_db_session must be an async generator function."""
        assert inspect.isasyncgenfunction(get_db_session), (
            "get_db_session must be an async generator function, "
            f"got {type(get_db_session)}"
        )

    def test_not_a_regular_function_returning_none(self) -> None:
        """get_db_session must NOT be a plain function (the old bug)."""
        assert not inspect.isfunction(get_db_session) or inspect.isasyncgenfunction(
            get_db_session
        ), "get_db_session should be async, not a plain function"


class TestGetDbSessionDegradedMode:
    """Tests for get_db_session when database is unavailable."""

    @pytest.mark.asyncio
    async def test_raises_503_when_get_session_is_none(self) -> None:
        """When _get_session is None, get_db_session raises HTTPException 503."""
        from fastapi import HTTPException

        with patch("graph_kb_api.dependencies._get_session", None):
            gen = get_db_session()
            with pytest.raises(HTTPException) as exc_info:
                await gen.__anext__()
            assert exc_info.value.status_code == 503
            assert "unavailable" in exc_info.value.detail.lower()


class TestGetDbSessionDelegation:
    """Tests for get_db_session delegation to base.get_session."""

    @pytest.mark.asyncio
    async def test_yields_session_from_base_get_session(self) -> None:
        """get_db_session yields the session produced by base.get_session."""
        mock_session = AsyncMock()

        async def fake_get_session():
            yield mock_session

        with patch("graph_kb_api.dependencies._get_session", fake_get_session):
            sessions = []
            async for session in get_db_session():
                sessions.append(session)

            assert len(sessions) == 1
            assert sessions[0] is mock_session

    @pytest.mark.asyncio
    async def test_yields_exactly_one_session(self) -> None:
        """get_db_session yields exactly one session per call."""
        mock_session = AsyncMock()

        async def fake_get_session():
            yield mock_session

        with patch("graph_kb_api.dependencies._get_session", fake_get_session):
            count = 0
            async for _ in get_db_session():
                count += 1
            assert count == 1
