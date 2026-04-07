"""
Centralized application settings for Graph KB API.

Single source of truth — all configuration comes from env vars / .env file.
Uses pydantic-settings for automatic loading, validation, and type coercion.

Usage:
    from graph_kb_api.config import settings
    settings.require_openai_api_key()
    print(settings.embedding_dimensions)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from graph_kb_api.core.models import OpenAIModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding model configs: dimensions and max tokens
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_CONFIGS = {
    "nomic-ai/nomic-embed-code": {"dimensions": 768, "max_tokens": 8192},
    "nomic-embed-code": {"dimensions": 768, "max_tokens": 8192},
    "all-MiniLM-L6-v2": {"dimensions": 384, "max_tokens": 512},
    "jinaai/jina-embeddings-v2-base-code": {"dimensions": 768, "max_tokens": 8192},
    "jinaai/jina-embeddings-v3": {"dimensions": 1024, "max_tokens": 8192},
    "text-embedding-3-large": {"dimensions": 3072, "max_tokens": 8191},
    "text-embedding-3-small": {"dimensions": 1536, "max_tokens": 8191},
    "text-embedding-ada-002": {"dimensions": 1536, "max_tokens": 8191},
}

DEFAULT_EMBEDDING_CONFIG = {"dimensions": 768, "max_tokens": 512}


# ---------------------------------------------------------------------------
# Nested config models (hardcoded defaults, not individually env-driven)
# ---------------------------------------------------------------------------


class SliderConfig(BaseModel):
    min: float
    max: float
    step: float
    description: str


class RetrievalDefaults(BaseModel):
    max_context_tokens: int = 100000
    top_k_vector: int = 2000
    graph_expansion_hops: int = 10
    max_expansion_nodes: int = 2000
    max_symbols_per_chunk: int = 3
    max_resolved_ids_per_symbol: int = 3
    max_entry_points_traced: int = 20
    max_context_items_for_flow: int = 10
    same_file_bonus: float = 0.1
    same_directory_bonus: float = 0.05
    tokens_per_line: float = 10.0
    max_depth: int = 50
    similarity_threshold: float = 0.7
    similarity_function: str = "cosine"
    include_visualization: bool = True
    include_related_symbols: bool = True
    enable_ranking: bool = True


class ChatUISliders(BaseModel):
    max_context_tokens: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=1000, max=200000, step=1000, description="Maximum tokens in context"
        )
    )
    top_k: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=5, max=5000, step=5, description="Number of top results to return"
        )
    )
    expansion_hops: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=1, max=10, step=1, description="Number of hops for graph expansion"
        )
    )
    max_depth: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=1, max=25, step=1, description="Maximum depth for graph traversal"
        )
    )
    max_expansion_nodes: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=100,
            max=2000,
            step=100,
            description="Maximum nodes per symbol expansion",
        )
    )
    max_entry_points_traced: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=1, max=20, step=1, description="Maximum entry points to trace for flows"
        )
    )
    same_file_bonus: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=0.0, max=0.5, step=0.05, description="Bonus for results in same file"
        )
    )
    same_directory_bonus: SliderConfig = Field(
        default_factory=lambda: SliderConfig(
            min=0.0,
            max=0.3,
            step=0.01,
            description="Bonus for results in same directory",
        )
    )


# ---------------------------------------------------------------------------
# Main Settings — single source of truth
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """All application config loaded from env vars / .env file.

    Priority: env vars > .env file > field defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── API ────────────────────────────────────────────────────────────
    graphkb_api_title: str = Field("Graph KB API", validation_alias="GRAPHKB_API_TITLE")
    graphkb_host: str = Field("0.0.0.0", validation_alias="GRAPHKB_HOST")
    graphkb_port: int = Field(8000, validation_alias="GRAPHKB_PORT")
    debug: bool = False

    @computed_field
    @property
    def api_title(self) -> str:
        return self.graphkb_api_title

    @computed_field
    @property
    def host(self) -> str:
        return self.graphkb_host

    @computed_field
    @property
    def port(self) -> int:
        return self.graphkb_port

    # ── API Keys ──────────────────────────────────────────────────────
    openai_api_key: Optional[str] = Field(None, validation_alias="OPENAI_API_KEY")
    github_token: Optional[str] = Field(None, validation_alias="GITHUB_TOKEN")

    # ── LLM Provider ──────────────────────────────────────────────────
    llm_provider: str = Field("openai", validation_alias="LLM_PROVIDER")
    ollama_base_url: str = Field(
        "http://host.docker.internal:11434", validation_alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field("mistral", validation_alias="OLLAMA_MODEL")

    # ── LLM Configuration ─────────────────────────────────────────────
    openai_model: str = Field(
        OpenAIModel.GPT_5_4.value, validation_alias="OPENAI_MODEL"
    )
    llm_temperature: float = Field(0.0, validation_alias="LLM_TEMPERATURE")
    llm_max_tokens: Optional[int] = Field(None, validation_alias="LLM_MAX_TOKENS")

    # ── LLM Recording / Mock ─────────────────────────────────────────
    llm_recording_mode: str = Field("off", validation_alias="LLM_RECORDING_MODE")
    llm_recording_dir: Optional[str] = Field(None, validation_alias="LLM_RECORDING_DIR")
    llm_mock_dir: Optional[str] = Field(None, validation_alias="LLM_MOCK_DIR")

    # ── Embedding ─────────────────────────────────────────────────────
    embedding_model: str = Field(
        "jinaai/jina-embeddings-v3", validation_alias="EMBEDDING_MODEL"
    )
    embedding_device: Optional[str] = Field(None, validation_alias="EMBEDDING_DEVICE")
    dimensions: Optional[int] = Field(1024, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_similarity: str = Field("cosine", validation_alias="EMBEDDING_SIMILARITY")

    # ── Chunking ──────────────────────────────────────────────────────
    chunk_size: int = Field(1000, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(200, validation_alias="CHUNK_OVERLAP")

    # ── Database (PostgreSQL) ─────────────────────────────────────────
    database_url: Optional[str] = Field(None, validation_alias="DATABASE_URL")
    database_pool_size: int = Field(10, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(20, validation_alias="DATABASE_MAX_OVERFLOW")

    # ── Neo4j ─────────────────────────────────────────────────────────
    neo4j_uri: str = Field("bolt://localhost:7687", validation_alias="NEO4J_URI")
    neo4j_user: str = Field("neo4j", validation_alias="NEO4J_USER")
    neo4j_password: str = Field("password", validation_alias="NEO4J_PASSWORD")
    neo4j_database: str = Field("neo4j", validation_alias="NEO4J_DATABASE")
    neo4j_max_pool_size: int = Field(50, validation_alias="NEO4J_MAX_POOL_SIZE")
    neo4j_connection_timeout: int = Field(
        300, validation_alias="NEO4J_CONNECTION_TIMEOUT"
    )

    # ── Neo4j Graph Store ─────────────────────────────────────────────
    graph_store_chunks_enabled: bool = Field(
        True, validation_alias="GRAPH_STORE_CHUNKS_ENABLED"
    )
    neo4j_store_chunk_embeddings: bool = Field(
        True, validation_alias="NEO4J_STORE_CHUNK_EMBEDDINGS"
    )
    neo4j_store_chunk_content: bool = Field(
        True, validation_alias="NEO4J_STORE_CHUNK_CONTENT"
    )
    neo4j_vector_index_name: str = Field(
        "chunk_embeddings", validation_alias="NEO4J_VECTOR_INDEX_NAME"
    )

    # ── ChromaDB ──────────────────────────────────────────────────────
    vector_db_path: str = Field("./chroma_db", validation_alias="VECTOR_DB_PATH")
    chroma_server_host: str = Field("localhost", validation_alias="CHROMA_SERVER_HOST")
    chroma_server_port: int = Field(8000, validation_alias="CHROMA_SERVER_PORT")
    chroma_collection_name: str = Field(
        "code_chunks", validation_alias="CHROMA_COLLECTION_NAME"
    )

    # ── Storage Paths ─────────────────────────────────────────────────
    storage_path: str = Field("./output_docs", validation_alias="STORAGE_PATH")
    repo_storage_path: str = Field("/data/repos", validation_alias="REPO_STORAGE_PATH")
    graph_kb_repo_path: str = Field(
        "/data/repos", validation_alias="GRAPH_KB_REPO_PATH"
    )
    max_context_tokens: int = Field(6000, validation_alias="MAX_CONTEXT_TOKENS")

    # ── CORS ──────────────────────────────────────────────────────────
    cors_origins: Optional[str] = Field(None, validation_alias="CORS_ORIGINS")
    graphkb_cors_origins: Optional[str] = Field(
        None, validation_alias="GRAPHKB_CORS_ORIGINS"
    )

    @computed_field
    @property
    def cors_origin_list(self) -> List[str]:
        raw = self.graphkb_cors_origins or self.cors_origins
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return ["*"]

    # ── Graph Traversal ───────────────────────────────────────────────
    max_depth: int = Field(25, validation_alias="MAX_DEPTH")

    # ── Agent Configuration ───────────────────────────────────────────
    show_agent_tool_calls: bool = Field(True, validation_alias="SHOW_AGENT_TOOL_CALLS")

    # ── Multi-Repo Research ───────────────────────────────────────────
    multi_repo_concurrency_limit: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="MULTI_REPO_CONCURRENCY_LIMIT",
        description="Maximum number of repositories researched concurrently in multi-repo mode",
    )
    deep_agent_max_iterations: int = Field(
        50, validation_alias="DEEP_AGENT_MAX_ITERATIONS"
    )

    # ── Timeouts (seconds) ────────────────────────────────────────────
    websocket_keepalive_interval: int = Field(
        25, validation_alias="CHAINLIT_KEEPALIVE_INTERVAL"
    )
    operation_timeout: int = Field(300, validation_alias="CHAINLIT_OPERATION_TIMEOUT")
    ask_code_timeout: int = Field(300, validation_alias="ASK_CODE_TIMEOUT")
    retrieval_timeout: int = Field(300, validation_alias="RETRIEVAL_TIMEOUT")
    deep_agent_timeout: int = Field(600, validation_alias="DEEP_AGENT_TIMEOUT")

    # ── Debug ─────────────────────────────────────────────────────────
    debug_log_to_file: bool = Field(False, validation_alias="DEBUG_LOG_TO_FILE")

    # ── LangGraph v3 ──────────────────────────────────────────────────
    langgraph_v3_enabled: bool = Field(False, validation_alias="LANGGRAPH_V3_ENABLED")
    langgraph_checkpointer_type: str = Field(
        "memory", validation_alias="LANGGRAPH_CHECKPOINTER_TYPE"
    )
    langgraph_postgres_uri: Optional[str] = Field(
        None, validation_alias="LANGGRAPH_POSTGRES_URI"
    )

    # ── Retrieval Defaults (hardcoded) ────────────────────────────────
    retrieval_defaults: RetrievalDefaults = Field(default_factory=RetrievalDefaults)

    # ── Chat UI Sliders (hardcoded) ───────────────────────────────────
    chat_ui_sliders: ChatUISliders = Field(default_factory=ChatUISliders)

    # ── Computed embedding properties ─────────────────────────────────

    @computed_field
    @property
    def embedding_dimensions(self) -> int:
        if self.dimensions is not None:
            return self.dimensions
        config = EMBEDDING_MODEL_CONFIGS.get(
            self.embedding_model, DEFAULT_EMBEDDING_CONFIG
        )
        return config["dimensions"]

    @computed_field
    @property
    def embedding_max_tokens(self) -> int:
        config = EMBEDDING_MODEL_CONFIGS.get(
            self.embedding_model, DEFAULT_EMBEDDING_CONFIG
        )
        return int(config["max_tokens"] / 4)

    @computed_field
    @property
    def llm_max_output_tokens(self) -> int:
        if self.llm_max_tokens is not None:
            return self.llm_max_tokens
        model_output_limits = {
            "gpt-4o": 4096,
            "gpt-4-turbo": 4096,
            "gpt-4.1": 32768,
            "gpt-5": 128000,
            "gpt-5.1": 128000,
            "gpt-5.2": 128000,
            "o1": 100000,
            "o3": 100000,
            "o4": 100000,
        }
        model_lower = self.openai_model.lower()
        for prefix, limit in model_output_limits.items():
            if model_lower.startswith(prefix):
                return limit
        return 4096

    # ── Validation & require helpers ──────────────────────────────────

    def validate_env(self) -> List[str]:
        """Log startup summary and return list of missing critical vars."""
        missing = []
        if self.llm_provider != "ollama" and not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not self.database_url:
            missing.append("DATABASE_URL")

        if missing:
            logger.warning(
                "Missing required environment variables: %s — some features will fail.",
                ", ".join(missing),
            )
        else:
            logger.info("All required environment variables are set")

        logger.info(
            "[Settings] LLM provider=%s, model=%s, api_key_set=%s",
            self.llm_provider,
            self.ollama_model if self.llm_provider == "ollama" else self.openai_model,
            bool(self.openai_api_key),
        )
        logger.info(
            "[Settings] Database URL set=%s, pool_size=%d, max_overflow=%d",
            bool(self.database_url),
            self.database_pool_size,
            self.database_max_overflow,
        )
        logger.info("[Settings] Neo4j uri=%s, user=%s", self.neo4j_uri, self.neo4j_user)
        logger.info(
            "[Settings] ChromaDB host=%s, port=%d",
            self.chroma_server_host,
            self.chroma_server_port,
        )
        return missing

    def require_openai_api_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
        return self.openai_api_key

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")
        return self.database_url


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
settings: Settings = Settings()
