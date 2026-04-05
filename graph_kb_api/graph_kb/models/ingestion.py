"""Ingestion-related data models."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .base import Chunk, Relationship, SymbolInfo
from .enums import IndexingPhase, Language


@dataclass
class IndexingProgress:
    """Progress information for repository indexing."""

    repo_id: str
    phase: IndexingPhase
    total_files: int = 0
    processed_files: int = 0
    current_file: Optional[str] = None
    total_chunks: int = 0
    total_symbols: int = 0
    total_relationships: int = 0
    errors: List[str] = field(default_factory=list)
    message: str = ""
    # Checkpoint tracking fields
    completed_files: int = 0
    failed_files: int = 0
    remaining_files: int = 0
    skipped_files: int = 0
    # Embedding progress tracking
    processed_chunks: int = 0
    total_chunks_to_embed: int = 0
    # V2-specific: relationship resolution stats
    resolved_relationships: int = 0
    external_relationships: int = 0
    unresolved_relationships: int = 0
    # Pass 2 progress tracking
    total_files_to_resolve: int = 0
    resolved_files: int = 0

    @property
    def progress_percent(self) -> float:
        """Get progress percentage based on current phase."""
        if self.phase == IndexingPhase.GENERATING_EMBEDDINGS:
            if self.total_chunks_to_embed == 0:
                return 0.0
            return (self.processed_chunks / self.total_chunks_to_embed) * 100
        if self.phase == IndexingPhase.RESOLVING_RELATIONSHIPS:
            if self.total_files_to_resolve == 0:
                return 0.0
            return (self.resolved_files / self.total_files_to_resolve) * 100
        if self.total_files == 0:
            return 0.0
        return (self.processed_files / self.total_files) * 100

    @property
    def is_complete(self) -> bool:
        return self.phase in (IndexingPhase.COMPLETED, IndexingPhase.ERROR, IndexingPhase.PAUSED)

    @property
    def has_errors(self) -> bool:
        """Check if any errors occurred during indexing."""
        return len(self.errors) > 0


@dataclass
class ResolutionStats:
    """Statistics from Pass 2 relationship resolution."""
    created: int = 0
    external: int = 0
    unresolved: int = 0


@dataclass
class FileIndexResult:
    """Result from Pass 1 file processing.

    Contains all data collected from processing a single file during Pass 1,
    including symbols, relationships, and chunk data needed for Pass 2
    relationship resolution.

    Attributes:
        file_path: Relative path to the file within the repository.
        file_node_id: Graph node ID for the file node created in Pass 1.
        language: Programming language of the file.
        symbols: List of all SymbolInfo objects extracted from the file.
        symbol_node_ids: Mapping from symbol_id to graph node_id for each symbol.
        relationships: List of all Relationship objects (both resolved and unresolved).
        chunks_with_file: List of (Chunk, file_node_id) tuples for chunk nodes.
        symbol_chunk_links: List of (symbol_node_id, chunk_node_id) tuples for linking.
    """

    file_path: str
    file_node_id: str
    language: Language
    symbols: List[SymbolInfo] = None
    symbol_node_ids: Dict[str, str] = None
    relationships: List[Relationship] = None
    chunks_with_file: List[Tuple[Chunk, str]] = None
    symbol_chunk_links: List[Tuple[str, str]] = None

    def __post_init__(self) -> None:
        """Initialize default values and validate required fields."""
        if self.symbols is None:
            self.symbols = []
        if self.symbol_node_ids is None:
            self.symbol_node_ids = {}
        if self.relationships is None:
            self.relationships = []
        if self.chunks_with_file is None:
            self.chunks_with_file = []
        if self.symbol_chunk_links is None:
            self.symbol_chunk_links = []

        # Validate required fields
        if not self.file_path:
            raise ValueError("file_path must be non-empty")
        if not self.file_node_id:
            raise ValueError("file_node_id must be non-empty")
