"""
Application context for Graph KB API.

Provides a singleton ``AppContext`` that bundles the settings, LLM service,
GraphKB facade, and checkpointer into a single object passed to workflow
engines and nodes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

if TYPE_CHECKING:
    from graph_kb_api.config.settings import Settings
    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.graph_kb.facade import GraphKBFacade
    from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig
    from graph_kb_api.services.mcp_service import MCPService
    from graph_kb_api.storage.blob_storage import BlobStorage

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Bundles application-wide services needed by workflow engines.

    Attributes:
        settings: Application settings loaded from env / .env.
        llm: The LLM service wrapper (``LLMService``).  Workflow engines
            that need the raw LangChain chat model access ``llm.llm``.
        graph_kb_facade: The initialized ``GraphKBFacade`` singleton.
        checkpointer: Optional LangGraph checkpointer for state persistence.
        mcp_service: Optional MCP service for external tool integration.
        blob_storage: Optional blob storage for workflow artifacts.
    """

    settings: Settings
    llm: LLMService
    graph_kb_facade: Optional[GraphKBFacade] = None
    checkpointer: Any = None
    mcp_service: Optional["MCPService"] = None
    blob_storage: Optional["BlobStorage"] = None

    def get_retrieval_settings(self) -> RetrievalConfig:
        """Return retrieval configuration derived from settings."""

        return RetrievalConfig.from_settings()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_app_context: Optional[AppContext] = None


def get_app_context() -> AppContext:
    """Return the global ``AppContext``, creating it lazily on first call.

    The context is built from the module-level ``settings`` singleton, a
    freshly-created ``LLMService``, and the ``GraphKBFacade`` (if available).
    The MCP service is initialized if the facade has a metadata store.
    """
    global _app_context
    if _app_context is not None:
        return _app_context

    from graph_kb_api.config.settings import settings
    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.dependencies import get_graph_kb_facade
    from graph_kb_api.services.mcp_service import MCPService
    from graph_kb_api.storage.blob_storage import BlobStorage

    llm_service = LLMService()

    try:
        facade = get_graph_kb_facade()
    except Exception:
        logger.warning("GraphKBFacade not available — AppContext will have no facade")
        facade = None

    # Initialize MCP service if metadata store is available
    mcp_service = None
    if facade is not None and facade.metadata_store is not None:
        try:
            mcp_service = MCPService(metadata_store=facade.metadata_store)
            logger.info("MCP service initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize MCP service: {e}")

    blob_storage = None
    try:
        blob_storage = BlobStorage.from_env()
        logger.info("Blob storage initialized")
    except Exception as exc:
        logger.warning("Blob storage not available in AppContext: %s", exc)

    _app_context = AppContext(
        settings=settings,
        llm=llm_service,
        graph_kb_facade=facade,
        mcp_service=mcp_service,
        blob_storage=blob_storage,
    )
    return _app_context
