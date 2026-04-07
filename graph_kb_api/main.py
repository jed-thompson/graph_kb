"""
FastAPI application entry point for Graph KB API.

This module creates and configures FastAPI application with:
- CORS middleware
- Exception handlers
- Startup/shutdown lifecycle events
- Router registration
- Database initialization
"""

import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from graph_kb_api.config import get_settings
from graph_kb_api.config import settings as app_settings
from graph_kb_api.database.base import close_database, init_database
from graph_kb_api.dependencies import (
    _init_facade,
    get_db_session,
    get_facade_error,
    get_graph_kb_facade,
    is_database_available,
    is_facade_available,
)
from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory
from graph_kb_api.graph_kb.models.exceptions import (
    RepositoryNotFoundError,
    SymbolNotFoundError,
)
from graph_kb_api.websocket import manager, process_message
from graph_kb_api.websocket.handlers.research_dispatcher import set_research_ws_manager

# Configure logging after imports
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("graph_kb_api").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown."""
    # Startup
    logger.info("Starting Graph KB API...")

    # Validate environment variables early

    app_settings.validate_env()

    # Initialize PostgreSQL database
    try:
        await init_database()
        logger.info("PostgreSQL database initialized")

        # Initialize LangGraph checkpointer pools and schemas
        await CheckpointerFactory.init_checkpointer()
    except Exception as e:
        logger.warning(f"PostgreSQL database not initialized: {e}")
        logger.warning("API will start but some endpoints may not work without database")

    # Try to initialize facade, but don't fail if app if it fails
    # This allows for health endpoints to work even without Neo4j/ChromaDB
    try:
        _init_facade()
        if is_facade_available():
            logger.info("Graph KB services initialized successfully")
        else:
            logger.warning(
                "Graph KB services not fully initialized: %s",
                get_facade_error() or "unknown",
            )
            logger.warning("API will start but some endpoints may not work without Neo4j/ChromaDB")
    except Exception as e:
        logger.warning(f"Graph KB services not fully initialized: {e}")
        logger.warning("API will start but some endpoints may not work without Neo4j/ChromaDB")

    # Initialize research WS manager (routing handled by main dispatcher)
    set_research_ws_manager(manager)

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down Graph KB API...")
    try:
        # Close PostgreSQL database
        await close_database()
        await CheckpointerFactory.close_checkpointer()

        logger.info("PostgreSQL database closed")

        facade = get_graph_kb_facade()
        if facade and facade.graph_store:
            facade.graph_store.close()
        logger.info("Graph KB services closed")
    except Exception as e:
        logger.warning(f"Error during shutdown: {e}")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    API_VERSION = "1.0.0"

    # CORS origins from settings (env-driven)
    cors_list = app_settings.cors_origin_list
    CORS_ORIGINS = (
        cors_list
        if cors_list != ["*"]
        else [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://localhost:8092",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8092",
        ]
    )

    app = FastAPI(
        title=app_settings.api_title,
        version=API_VERSION,
        description="REST and WebSocket API for code knowledge graph operations",
        lifespan=lifespan,
    )

    # CORS Middleware
    # Security: Only enable credentials when using specific origins (not wildcard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=len(CORS_ORIGINS) > 0
        and CORS_ORIGINS[0] != "*",  # Only allow credentials with specific origins
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,  # Cache preflight requests for 10 minutes
    )

    # Exception Handlers
    @app.exception_handler(RepositoryNotFoundError)
    async def repo_not_found_handler(request: Request, exc: RepositoryNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_type": "repository_not_found"},
        )

    @app.exception_handler(SymbolNotFoundError)
    async def symbol_not_found_handler(request: Request, exc: SymbolNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_type": "symbol_not_found"},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_type": "internal_error"},
        )

    # Health Check Endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint.

        Reports degraded status when the database or graph services are
        unreachable, and lists which services are available vs degraded.
        """
        db_available = is_database_available()
        facade_available = is_facade_available()

        # Determine per-service status from the facade
        neo4j_ok = False
        chromadb_ok = False
        llm_ok = False
        if facade_available:
            try:
                facade = get_graph_kb_facade()
                neo4j_ok = facade.graph_store is not None
                chromadb_ok = facade.vector_store is not None
                llm_ok = hasattr(facade, "llm_service") and facade.llm_service is not None
            except Exception:
                pass

        all_ok = db_available and facade_available
        status = "ok" if all_ok else "degraded"

        return {
            "status": status,
            "version": API_VERSION,
            "services": {
                "database": "available" if db_available else "unavailable",
                "neo4j": "available" if neo4j_ok else "unavailable",
                "chromadb": "available" if chromadb_ok else "unavailable",
                "llm": "available" if llm_ok else "unavailable",
            },
        }

    @app.get("/api/v1/health", tags=["Health"])
    async def api_health_check():
        """API health check with detailed service status."""
        db_available = is_database_available()
        facade_available = is_facade_available()

        neo4j_ok = False
        chromadb_ok = False
        llm_ok = False
        if facade_available:
            try:
                facade = get_graph_kb_facade()
                neo4j_ok = facade.graph_store is not None
                chromadb_ok = facade.vector_store is not None
                llm_ok = hasattr(facade, "llm_service") and facade.llm_service is not None
            except Exception:
                pass

        all_ok = db_available and neo4j_ok and chromadb_ok
        return {
            "status": "ok" if all_ok else "degraded",
            "version": API_VERSION,
            "services": {
                "database": "available" if db_available else "unavailable",
                "neo4j": "available" if neo4j_ok else "unavailable",
                "chromadb": "available" if chromadb_ok else "unavailable",
                "llm": "available" if llm_ok else "unavailable",
                "graph_kb": "available" if facade_available else "unavailable",
            },
            "facade_error": get_facade_error(),
        }

    # Database Health Check Endpoint
    @app.get("/health/db", tags=["Health"])
    async def database_health_check(db: AsyncSession = Depends(get_db_session)):
        """Database health check endpoint.

        Checks PostgreSQL connectivity and critical tables.
        """

        status = "ok"
        tables_check: dict[str, dict[str, bool | int]] = {}
        checks: dict[str, str | dict[str, dict[str, bool | int]]] = {
            "database": "connected",
            "tables": tables_check,
        }

        try:
            # Test connection
            result = await db.execute(text("SELECT 1"))
            result.scalar()

            # Check for tables
            tables_to_check = ["repositories", "documents", "file_index"]
            for table_name in tables_to_check:
                result = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar() or 0
                tables_check[table_name] = {
                    "exists": count > 0,
                    "rows": count,
                }

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            status = "error"
            checks["database"] = f"Error: {str(e)}"

        return {
            "status": status,
            "checks": checks,
            "version": API_VERSION,
        }

    # Register routers
    from graph_kb_api.routers import (
        analysis_router,
        artifacts_router,
        chat_router,
        documents_router,
        plan_sessions_router,
        repos_router,
        search_router,
        settings_router,
        sources_router,
        steering_router,
        symbols_router,
        templates_router,
        visualization_router,
    )

    app.include_router(artifacts_router, prefix="/api/v1")
    app.include_router(repos_router, prefix="/api/v1")
    app.include_router(symbols_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(analysis_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(steering_router, prefix="/api/v1")
    app.include_router(visualization_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(settings_router, prefix="/api/v1")
    app.include_router(templates_router, prefix="/api/v1")
    app.include_router(sources_router, prefix="/api/v1")
    app.include_router(plan_sessions_router, prefix="/api/v1")

    # WebSocket endpoints
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        Main WebSocket endpoint for all workflows.

        Clients send messages to start/interact with workflows.
        Server sends events for progress/results.

        Accepts an optional ``client_id`` query parameter so the frontend
        can supply a persistent browser identity for session continuity
        between REST and WebSocket contexts.
        """
        client_id: str = websocket.query_params.get("client_id") or str(uuid.uuid4())
        await manager.connect(websocket, client_id)

        try:
            while True:
                data = await websocket.receive_json()
                await process_message(client_id, websocket, data)
        except WebSocketDisconnect:
            await manager.disconnect(client_id)
        except RuntimeError:
            await manager.disconnect(client_id)

    @app.websocket("/ws/ask-code")
    async def ask_code_websocket(websocket: WebSocket):
        """Dedicated endpoint for ask-code workflow."""
        client_id = str(uuid.uuid4())
        await manager.connect(websocket, client_id)

        try:
            while True:
                data = await websocket.receive_json()
                # Auto-set workflow type
                data["payload"] = data.get("payload", {})
                data["payload"]["workflow_type"] = "ask-code"
                await process_message(client_id, websocket, data)
        except WebSocketDisconnect:
            await manager.disconnect(client_id)
        except RuntimeError:
            await manager.disconnect(client_id)

    @app.websocket("/ws/ingest")
    async def ingest_websocket(websocket: WebSocket):
        """Dedicated endpoint for ingest workflow."""
        client_id = str(uuid.uuid4())
        await manager.connect(websocket, client_id)

        try:
            while True:
                data = await websocket.receive_json()
                data["payload"] = data.get("payload", {})
                data["payload"]["workflow_type"] = "ingest"
                await process_message(client_id, websocket, data)
        except WebSocketDisconnect:
            await manager.disconnect(client_id)
        except RuntimeError:
            await manager.disconnect(client_id)

    return app


# Application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "graph_kb_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
