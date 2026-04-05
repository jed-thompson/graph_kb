"""Processing-related data models.

This module contains data models specific to content processing operations,
including text chunking and vector embedding generation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ChunkType(Enum):
    """Types of content chunks."""
    CODE = "code"
    DOCSTRING = "docstring"
    COMMENT = "comment"
    TEXT = "text"
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    MIXED = "mixed"


class EmbeddingModel(Enum):
    """Supported embedding models."""
    JINA_V3 = "jinaai/jina-embeddings-v3"
    OPENAI_ADA = "text-embedding-ada-002"
    OPENAI_3_SMALL = "text-embedding-3-small"
    OPENAI_3_LARGE = "text-embedding-3-large"
    SENTENCE_TRANSFORMERS = "sentence-transformers/all-MiniLM-L6-v2"
    CUSTOM = "custom"


@dataclass
class Chunk:
    """A chunk of content for processing."""
    chunk_id: str
    content: str
    file_path: str
    repo_id: str
    start_line: int
    end_line: int
    chunk_type: ChunkType
    language: Optional[str] = None
    symbols_defined: List[str] = field(default_factory=list)
    symbols_referenced: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_count: Optional[int] = None
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ChunkingConfig:
    """Configuration for content chunking."""
    max_chunk_size: int = 1000
    overlap: int = 100
    preserve_structure: bool = True
    chunk_by_function: bool = True
    chunk_by_class: bool = True
    include_docstrings: bool = True
    include_comments: bool = False
    min_chunk_size: int = 50
    respect_boundaries: bool = True  # Don't split across logical boundaries


@dataclass
class ChunkingResult:
    """Result of content chunking operation."""
    chunks: List[Chunk]
    total_chunks: int
    total_tokens: int
    chunking_time: float
    strategy_used: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Embedding:
    """Vector embedding for a chunk."""
    chunk_id: str
    vector: List[float]
    model_name: str
    dimensions: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    model_name: str = "jinaai/jina-embeddings-v3"
    dimensions: int = 1024
    batch_size: int = 32
    max_tokens: int = 8192
    device: str = "cpu"
    normalize: bool = True
    timeout: float = 120.0  # seconds per batch
    retry_attempts: int = 3


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    embeddings: List[Embedding]
    total_embeddings: int
    successful_embeddings: int
    failed_embeddings: int
    generation_time: float
    model_used: str
    errors: List[str] = field(default_factory=list)


@dataclass
class BatchEmbeddingResult:
    """Result of batch embedding generation with error handling."""
    embeddings: List[Optional[List[float]]]
    successful_indices: List[int]
    failed_indices: List[int]
    errors: Dict[int, str] = field(default_factory=dict)
    has_failures: bool = False
    failure_count: int = 0
    success_count: int = 0
    total_time: float = 0.0


@dataclass
class ProcessingStats:
    """Statistics from processing operations."""
    total_files_processed: int
    total_chunks_created: int
    total_embeddings_generated: int
    chunks_by_type: Dict[ChunkType, int] = field(default_factory=dict)
    average_chunk_size: float = 0.0
    total_processing_time: float = 0.0
    embedding_success_rate: float = 0.0


@dataclass
class SubprocessEmbeddingConfig:
    """Configuration for subprocess-based embedding."""
    model_name: str = "jinaai/jina-embeddings-v3"
    device: Optional[str] = None
    timeout_per_chunk: float = 120.0
    max_retries: int = 3
    memory_limit: Optional[int] = None  # MB
    python_executable: str = "python"


@dataclass
class SubprocessEmbeddingResult:
    """Result from subprocess embedding operation."""
    chunk_id: str
    embedding: Optional[List[float]]
    success: bool
    error_message: Optional[str] = None
    processing_time: float = 0.0
    memory_used: Optional[int] = None  # MB
