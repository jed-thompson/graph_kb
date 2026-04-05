"""
Dependency injection for Graph KB API.

Provides FastAPI dependencies for accessing services and facades.
Uses @lru_cache for singleton pattern.  Supports graceful degradation
when Neo4j, ChromaDB, or PostgreSQL are unavailable — the API still
starts and serves endpoints that don't require those services.
"""

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from graph_kb_api.graph_kb.facade import GraphKBFacade
    from graph_kb_api.graph_kb.services.analysis_service import CodeAnalysisService
    from graph_kb_api.graph_kb.services.ingestion_service import IngestionService
    from graph_kb_api.graph_kb.services.query_service import CodeQueryService
    from graph_kb_api.graph_kb.services.retrieval_service import CodeRetrievalService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database session provider
# ---------------------------------------------------------------------------

_get_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None

try:
    from graph_kb_api.database.base import get_session as _base_get_session

    _get_session = _base_get_session
except Exception as e:
    logger.warning(
        "Database module not available — running in degraded mode: %s",
        e,
        exc_info=True,
    )

# ---------------------------------------------------------------------------
# Facade initialisation with graceful degradation
# ---------------------------------------------------------------------------
# The facade wraps Neo4j and ChromaDB.  If either is unavailable the API
# still starts — endpoints that don't need those services keep working.
# Endpoints that *do* need them receive a 503 via ``require_facade``.
# ---------------------------------------------------------------------------

_facade_instance: "GraphKBFacade | None" = None
_facade_error: str | None = None


def _init_facade() -> "GraphKBFacade | None":
    """Attempt to create and initialise the facade singleton.

    Returns the facade on success, or ``None`` if Neo4j / ChromaDB is
    unreachable.  The error message is stored in ``_facade_error`` so
    the health endpoint can report it.
    """
    global _facade_instance, _facade_error
    if _facade_instance is not None:
        return _facade_instance
    try:
        from graph_kb_api.graph_kb.facade import get_facade

        facade: GraphKBFacade = get_facade()
        if not facade.is_initialized:
            facade.initialize()
        _facade_instance = facade
        _facade_error = None
        return facade
    except Exception as exc:
        _facade_error = str(exc)
        logger.error(
            "GraphKBFacade not available — Neo4j/ChromaDB may be down: %s",
            exc,
            exc_info=True,
        )
        return None


def get_graph_kb_facade() -> "GraphKBFacade":
    """Get the singleton GraphKBFacade instance.

    Returns the facade if available.  If Neo4j or ChromaDB is down the
    first call stores the error; subsequent calls re-attempt once before
    raising 503.
    """
    global _facade_instance, _facade_error
    if _facade_instance is not None:
        return _facade_instance

    facade = _init_facade()
    if facade is not None:
        return facade

    # Re-attempt in case the service just came back
    facade = _init_facade()
    if facade is not None:
        return facade

    raise HTTPException(
        status_code=503,
        detail=f"Graph KB services unavailable: {_facade_error or 'Neo4j/ChromaDB unreachable'}",
    )


def require_facade() -> "GraphKBFacade":
    """FastAPI dependency that returns the facade or 503.

    Use this for endpoints that *require* Neo4j / ChromaDB.
    """
    return get_graph_kb_facade()


def is_facade_available() -> bool:
    """Return ``True`` when the facade has been successfully initialised."""
    return _facade_instance is not None and _facade_instance.is_initialized


def get_facade_error() -> str | None:
    """Return the last facade initialisation error, if any."""
    return _facade_error


# ---------------------------------------------------------------------------
# Service dependencies
# ---------------------------------------------------------------------------


def get_query_service(
    facade: "GraphKBFacade" = Depends(get_graph_kb_facade),
) -> "CodeQueryService":
    """Get the CodeQueryService for symbol queries."""
    assert facade.query_service is not None
    return facade.query_service


def get_retrieval_service(
    facade: "GraphKBFacade" = Depends(get_graph_kb_facade),
) -> "CodeRetrievalService":
    """Get the CodeRetrievalService for semantic search."""
    assert facade.retrieval_service is not None
    return facade.retrieval_service


def get_analysis_service(
    facade: "GraphKBFacade" = Depends(get_graph_kb_facade),
) -> "CodeAnalysisService":
    """Get the CodeAnalysisService for code analysis."""
    assert facade.analysis_service is not None
    return facade.analysis_service


def get_ingestion_service(
    facade: "GraphKBFacade" = Depends(get_graph_kb_facade),
) -> "IngestionService":
    """Get the IngestionService for repository indexing."""
    assert facade.ingestion_service is not None
    return facade.ingestion_service


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def is_database_available() -> bool:
    """Check whether the database is reachable."""
    if _get_session is None:
        return False
    try:
        from graph_kb_api.database.base import _async_session_maker

        return _async_session_maker is not None
    except Exception:
        return False


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for FastAPI dependency injection.

    Delegates to :func:`graph_kb_api.database.base.get_session` which
    handles commit on success, rollback on exception, and session close.

    Raises:
        HTTPException(503): If the database is unavailable.
    """
    if _get_session is None:
        raise HTTPException(
            status_code=503,
            detail="Database service unavailable",
        )

    async with _get_session() as session:
        yield session
