"""Base data models for the graph knowledge base."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from graph_kb_api.config import (
    DEFAULT_EMBEDDING_CONFIG,
    EMBEDDING_MODEL_CONFIGS,
    settings,
)

from .enums import (
    ContextItemType,
    DeletionPhase,
    DocumentStatus,
    FileStatus,
    GraphEdgeType,
    GraphNodeType,
    Language,
    RelationshipType,
    RepoStatus,
    SymbolKind,
    Visibility,
)


@dataclass
class RepoMetadata:
    """Repository metadata and indexing status."""

    repo_id: str
    git_url: str
    default_branch: str
    local_path: str
    last_indexed_commit: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    status: RepoStatus = RepoStatus.PENDING
    error_message: Optional[str] = None


@dataclass
class DocumentMetadata:
    """Document metadata and ingestion status."""

    doc_id: str
    original_name: str
    file_path: Optional[str] = None
    parent_name: Optional[str] = None
    category: Optional[str] = None
    collection_name: Optional[str] = None
    file_hash: Optional[str] = None
    chunk_count: int = 0
    status: DocumentStatus = DocumentStatus.PENDING
    error_message: Optional[str] = None


@dataclass
class ParameterInfo:
    """Information about a function/method parameter."""

    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    is_variadic: bool = False  # *args
    is_keyword: bool = False  # **kwargs


@dataclass
class SymbolInfo:
    """Information about a code symbol with enhanced metadata."""

    symbol_id: str
    name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int
    visibility: Visibility
    docstring: Optional[str] = None
    parent_symbol: Optional[str] = None
    # Enhanced metadata
    signature: Optional[str] = None  # Full function/method signature
    parameters: List[ParameterInfo] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    base_classes: List[str] = field(default_factory=list)  # For classes
    implemented_interfaces: List[str] = field(default_factory=list)
    is_async: bool = False
    is_static: bool = False
    is_abstract: bool = False
    complexity: Optional[int] = None  # Cyclomatic complexity estimate


@dataclass
class Relationship:
    """Relationship between two symbols with ID-based resolution support."""

    from_symbol: str
    to_symbol: str
    relationship_type: RelationshipType
    line_number: Optional[int] = None
    confidence: float = 1.0
    context: Optional[str] = None  # Additional context about the relationship

    # Optional: keep name for debugging/display
    from_symbol_name: Optional[str] = None
    to_symbol_name: Optional[str] = None

    # NEW: ID-based resolution fields for cross-file support
    from_symbol_id: Optional[str] = None  # Full symbol ID: file:name:kind:line
    to_symbol_id: Optional[str] = None    # None if unresolved (cross-file)

    # NEW: Cross-file resolution metadata
    to_module_path: Optional[str] = None  # e.g., "utils.auth" for import resolution
    imported_names: List[str] = field(default_factory=list)  # Names imported from module

    # NEW: Resolution status flags
    is_resolved: bool = False  # True if target has been resolved to a node
    is_external: bool = False  # True if target is an external library

@dataclass
class Chunk:
    """A semantically coherent unit of code or documentation."""

    chunk_id: str
    repo_id: str
    file_path: str
    language: Language
    start_line: int
    end_line: int
    content: str
    symbols_defined: List[str]
    symbols_referenced: List[str]
    commit_sha: str
    created_at: datetime
    # New fields for graph integration
    embedding: Optional[List[float]] = None  # Vector embedding
    token_count: Optional[int] = None
    chunk_type: str = "code"  # code, docstring, comment, config

    def to_json(self) -> str:
        """Serialize chunk to JSON string."""
        data = asdict(self)
        data["language"] = self.language.value
        data["created_at"] = self.created_at.isoformat()
        # Don't serialize embedding to JSON (too large)
        data.pop("embedding", None)
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "Chunk":
        """Deserialize chunk from JSON string."""
        data = json.loads(json_str)
        data["language"] = Language(data["language"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class GraphNode:
    """A node in the code graph."""

    id: str
    type: GraphNodeType
    repo_id: str
    attrs: Dict[str, Any]
    summary: Optional[str] = None
    embedding: Optional[List[float]] = None  # For Chunk nodes

    def to_json(self) -> str:
        """Serialize node to JSON string."""
        data = asdict(self)
        data["type"] = self.type.value
        # Don't serialize embedding to JSON
        data.pop("embedding", None)
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "GraphNode":
        """Deserialize node from JSON string."""
        data = json.loads(json_str)
        data["type"] = GraphNodeType(data["type"])
        return cls(**data)


@dataclass
class GraphEdge:
    """An edge in the code graph."""

    id: str
    from_node: str
    to_node: str
    edge_type: GraphEdgeType
    attrs: Dict[str, Any]

    def to_json(self) -> str:
        """Serialize edge to JSON string."""
        data = asdict(self)
        data["edge_type"] = self.edge_type.value
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "GraphEdge":
        """Deserialize edge from JSON string."""
        data = json.loads(json_str)
        data["edge_type"] = GraphEdgeType(data["edge_type"])
        return cls(**data)


@dataclass
class ChunkMetadata:
    """Metadata associated with a chunk in the vector store."""

    repo_id: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    symbols_defined: List[str]
    symbols_referenced: List[str]
    commit_sha: str
    ts_indexed: datetime


@dataclass
class Anchors:
    """Contextual anchors for focused retrieval."""

    current_file: Optional[str] = None
    selected_range: Optional[Dict[str, int]] = None  # {"start_line": int, "end_line": int}
    error_stack: Optional[str] = None


@dataclass
class DirectorySummary:
    """Summary information about a directory/module."""

    path: str
    file_count: int
    symbol_count: int
    files: List[str]
    main_symbols: List[str]
    description: Optional[str] = None
    incoming_deps: List[str] = field(default_factory=list)
    outgoing_deps: List[str] = field(default_factory=list)


@dataclass
class ContextItem:
    """An item in the retrieval response context."""

    type: ContextItemType
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    content: Optional[str] = None
    symbol: Optional[str] = None
    score: Optional[float] = None
    description: Optional[str] = None
    nodes: Optional[List[str]] = None
    directory_path: Optional[str] = None
    directory_summary: Optional[DirectorySummary] = None
    # New: graph distance for hybrid scoring
    graph_distance: Optional[int] = None


@dataclass
class RetrievalResponse:
    """Response from the retrieval API."""

    context_items: List[ContextItem]


def _get_default_embedding_config():
    """Get default embedding config from centralized settings."""
    from graph_kb_api.config import settings
    return {
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "max_tokens": settings.embedding_max_tokens,
    }


# OpenAI embedding models (require API, not local SentenceTransformers)
OPENAI_EMBEDDING_MODELS = {
    "text-embedding-3-large",
    "text-embedding-3-small",
    "text-embedding-ada-002",
}


def _is_openai_model(model_name: str) -> bool:
    """Check if a model name is an OpenAI embedding model."""
    return model_name in OPENAI_EMBEDDING_MODELS or model_name.startswith("text-embedding-")


@dataclass
class IngestionConfig:
    """Configuration for repository ingestion."""

    max_repo_size_mb: int = 1024
    max_file_size_kb: int = 256
    include_extensions: List[str] = field(
        default_factory=lambda: [
            ".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".java",
            ".rb", ".rs", ".c", ".cpp", ".cs", ".yaml", ".yml",
            ".json", ".md",
        ]
    )
    extra_exclude_patterns: List[str] = field(
        default_factory=lambda: [
            "**/node_modules/**", "node_modules/**",
            "**/dist/**", "dist/**",
            "**/*.min.js",
            "**/.venv/**", ".venv/**",
        ]
    )
    # Embedding configuration - defaults pulled from centralized settings
    embedding_provider: Optional[str] = None  # None = auto-detect from model, "local" or "openai"
    embedding_model: Optional[str] = None  # None = use settings.embedding_model
    embedding_dimensions: Optional[int] = None  # None = auto from model config
    max_chunk_tokens: Optional[int] = None  # None = auto from model config
    store_embeddings_in_neo4j: bool = True  # Enable Neo4j vector index
    # Parallel indexing configuration
    max_indexing_workers: int = 12  # Number of concurrent file indexing workers
    # Indexer version: v2 (two-pass with cross-file resolution)
    indexer_version: str = "v2"  # Always use v2 for cross-file relationship resolution

    def __post_init__(self):
        """Resolve None values from centralized settings and auto-detect provider."""

        if self.embedding_model is None:
            self.embedding_model = settings.embedding_model

        # Auto-detect embedding provider if not explicitly set
        if self.embedding_provider is None:
            if _is_openai_model(self.embedding_model):
                self.embedding_provider = "openai"
            else:
                self.embedding_provider = "local"

        model_config = EMBEDDING_MODEL_CONFIGS.get(self.embedding_model, DEFAULT_EMBEDDING_CONFIG)

        if self.embedding_dimensions is None:
            self.embedding_dimensions = model_config["dimensions"]

        if self.max_chunk_tokens is None:
            self.max_chunk_tokens = model_config["max_tokens"]

        # Validate indexer_version - only v2 is supported (v1 is deprecated)
        if self.indexer_version != "v2":
            raise ValueError(
                f"Invalid indexer_version '{self.indexer_version}'. "
                f"Only 'v2' is supported (v1 is deprecated)."
            )


@dataclass
class DeletionProgress:
    """Progress information for repository deletion.

    Tracks the deletion progress through each phase and store,
    including counts of deleted items and any errors encountered.
    """

    repo_id: str
    phase: DeletionPhase = DeletionPhase.INITIALIZING
    chroma_deleted: int = 0
    neo4j_chunks_deleted: int = 0
    neo4j_symbols_deleted: int = 0
    neo4j_files_deleted: int = 0
    neo4j_directories_deleted: int = 0
    errors: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def total_deleted(self) -> int:
        """Get total count of deleted items across all stores."""
        return (
            self.chroma_deleted
            + self.neo4j_chunks_deleted
            + self.neo4j_symbols_deleted
            + self.neo4j_files_deleted
            + self.neo4j_directories_deleted
        )

    @property
    def has_errors(self) -> bool:
        """Check if any errors occurred during deletion."""
        return len(self.errors) > 0



@dataclass
class FileIndexStatus:
    """Tracks indexing status for individual files within a repository.

    Used for checkpoint/resume capability during repository ingestion.
    """

    repo_id: str
    file_path: str
    file_hash: str
    status: FileStatus
    chunk_count: int = 0
    symbol_count: int = 0
    error_message: Optional[str] = None
    indexed_at: Optional[datetime] = None
