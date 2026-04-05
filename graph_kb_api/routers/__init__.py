"""
API Routers for Graph KB.
"""

from graph_kb_api.routers.analysis import router as analysis_router
from graph_kb_api.routers.artifacts import router as artifacts_router
from graph_kb_api.routers.chat import router as chat_router
from graph_kb_api.routers.documents import router as documents_router
from graph_kb_api.routers.plan import router as plan_sessions_router
from graph_kb_api.routers.repos import router as repos_router
from graph_kb_api.routers.search import router as search_router
from graph_kb_api.routers.settings import router as settings_router
from graph_kb_api.routers.sources import router as sources_router
from graph_kb_api.routers.steering import router as steering_router
from graph_kb_api.routers.symbols import router as symbols_router
from graph_kb_api.routers.templates import router as templates_router
from graph_kb_api.routers.visualization import router as visualization_router

__all__ = [
    "artifacts_router",
    "repos_router",
    "symbols_router",
    "search_router",
    "analysis_router",
    "documents_router",
    "steering_router",
    "visualization_router",
    "chat_router",
    "settings_router",
    "templates_router",
    "sources_router",
    "plan_sessions_router",
]
