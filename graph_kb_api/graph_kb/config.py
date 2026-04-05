"""Configuration classes for the graph knowledge base module.

All values are sourced from the centralized settings singleton.
"""

from dataclasses import dataclass
from typing import Literal

from graph_kb_api.config import settings


@dataclass
class Neo4jConfig:
    """Configuration for Neo4j graph database connection."""

    uri: str
    user: str
    password: str
    database: str = "neo4j"
    max_pool_size: int = 50
    connection_timeout: int = 300

    @classmethod
    def from_env(cls) -> "Neo4jConfig":
        return cls(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            max_pool_size=settings.neo4j_max_pool_size,
            connection_timeout=settings.neo4j_connection_timeout,
        )


@dataclass
class ChromaConfig:
    """Configuration for ChromaDB vector store connection."""

    host: str
    port: int
    collection_name: str = "code_chunks"

    @classmethod
    def from_env(cls) -> "ChromaConfig":
        return cls(
            host=settings.chroma_server_host,
            port=settings.chroma_server_port,
            collection_name=settings.chroma_collection_name,
        )

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


# Neo4j vector index has a maximum dimension limit
NEO4J_MAX_VECTOR_DIMENSIONS = 2048


@dataclass
class DualWriteConfig:
    """Configuration for dual-write embedding storage.

    Controls whether embeddings are written to Neo4j in addition to ChromaDB.
    Neo4j vector index supports a maximum of 2048 dimensions — if
    embedding_dimensions > 2048, neo4j_store_chunk_embeddings is auto-disabled.
    """

    graph_store_chunks_enabled: bool = True
    neo4j_store_chunk_embeddings: bool = True
    neo4j_store_chunk_content: bool = True
    neo4j_vector_index_name: str = "chunk_embeddings"
    embedding_dimensions: int = 768
    embedding_similarity: Literal["cosine", "euclidean"] = "cosine"

    def __post_init__(self):
        if self.embedding_dimensions > NEO4J_MAX_VECTOR_DIMENSIONS:
            from graph_kb_api.utils.enhanced_logger import EnhancedLogger

            logger = EnhancedLogger(__name__)
            logger.warning(
                f"Embedding dimensions ({self.embedding_dimensions}) exceed Neo4j limit "
                f"({NEO4J_MAX_VECTOR_DIMENSIONS}). Disabling Neo4j chunk embeddings."
            )
            self.neo4j_store_chunk_embeddings = False

    @classmethod
    def from_env(cls) -> "DualWriteConfig":
        from graph_kb_api.config import settings

        return cls(
            graph_store_chunks_enabled=settings.graph_store_chunks_enabled,
            neo4j_store_chunk_embeddings=settings.neo4j_store_chunk_embeddings,
            neo4j_store_chunk_content=settings.neo4j_store_chunk_content,
            neo4j_vector_index_name=settings.neo4j_vector_index_name,
            embedding_dimensions=settings.embedding_dimensions,
            embedding_similarity=settings.embedding_similarity,  # type: ignore
        )


@dataclass
class GraphKBConfig:
    """Combined configuration for the graph knowledge base."""

    neo4j: Neo4jConfig
    chroma: ChromaConfig
    dual_write: DualWriteConfig
    repo_storage_path: str = "/data/repos"
    embedding_model: str = "text-embedding-3-small"
    max_context_tokens: int = 6000

    @classmethod
    def from_env(cls) -> "GraphKBConfig":
        return cls(
            neo4j=Neo4jConfig.from_env(),
            chroma=ChromaConfig.from_env(),
            dual_write=DualWriteConfig.from_env(),
            repo_storage_path=settings.repo_storage_path,
            embedding_model=settings.embedding_model,
            max_context_tokens=settings.max_context_tokens,
        )
