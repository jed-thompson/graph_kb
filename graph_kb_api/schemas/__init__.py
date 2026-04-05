"""
Pydantic schemas for Graph KB API.
"""

from graph_kb_api.schemas.chat import (
    AskCodeRequest,
    AskCodeResponse,
    SourceItem,
)
from graph_kb_api.schemas.common import (
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
    PaginationParams,
)
from graph_kb_api.schemas.documents import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadRequest,
)
from graph_kb_api.schemas.intent import (
    IntentConfig,
    IntentResult,
)
from graph_kb_api.schemas.repos import (
    RepoCreateRequest,
    RepoListResponse,
    RepoResponse,
    RepoStatus,
)
from graph_kb_api.schemas.retrieval import (
    ContextItemResponse,
    RetrieveRequest,
    RetrieveResponse,
    SearchRequest,
    SearchResponse,
)
from graph_kb_api.schemas.settings import (
    SettingsResponse,
    SettingsUpdateRequest,
)
from graph_kb_api.schemas.steering import (
    SteeringDocResponse,
    SteeringListResponse,
)
from graph_kb_api.schemas.symbols import (
    PathRequest,
    PathResponse,
    SymbolKind,
    SymbolNeighborsRequest,
    SymbolResponse,
    SymbolSearchRequest,
)
from graph_kb_api.schemas.upload import (
    FileUploadClassification,
    FileUploadResult,
)
from graph_kb_api.schemas.visualization import (
    VisualizationEdge,
    VisualizationNode,
    VisualizationResponse,
)
from graph_kb_api.schemas.websocket import (
    WSInputPayload,
    WSMessage,
    WSOutgoingMessage,
    WSStartPayload,
)

__all__ = [
    # Common
    "ErrorResponse",
    "PaginationParams",
    "PaginatedResponse",
    "HealthResponse",
    # Repos
    "RepoStatus",
    "RepoResponse",
    "RepoListResponse",
    "RepoCreateRequest",
    # Symbols
    "SymbolKind",
    "SymbolResponse",
    "SymbolSearchRequest",
    "SymbolNeighborsRequest",
    "PathRequest",
    "PathResponse",
    # Retrieval
    "SearchRequest",
    "SearchResponse",
    "ContextItemResponse",
    "RetrieveRequest",
    "RetrieveResponse",
    # Documents
    "DocumentResponse",
    "DocumentListResponse",
    "DocumentUploadRequest",
    # Steering
    "SteeringDocResponse",
    "SteeringListResponse",
    # Visualization
    "VisualizationNode",
    "VisualizationEdge",
    "VisualizationResponse",
    # Chat
    "AskCodeRequest",
    "SourceItem",
    "AskCodeResponse",
    # Settings
    "SettingsResponse",
    "SettingsUpdateRequest",
    # Intent
    "IntentResult",
    "IntentConfig",
    # WebSocket
    "WSMessage",
    "WSStartPayload",
    "WSInputPayload",
    "WSOutgoingMessage",
    # Upload
    "FileUploadClassification",
    "FileUploadResult",
]
