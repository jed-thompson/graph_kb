"""Ingestion Service for orchestrating the repository ingestion pipeline.

This service follows the orchestration pattern by delegating to domain modules
while preserving all existing functionality from IndexerService.
"""

from typing import Callable, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..config import DualWriteConfig
from ..models.base import IngestionConfig
from ..models.enums import RepoStatus
from ..models.ingestion import IndexingProgress
from ..parsing.language_parser import LanguageParser
from ..parsing.symbol_extractor import SymbolExtractor
from ..processing.chunker import Chunker
from ..processing.embedding_generator import EmbeddingGenerator
from ..repositories.file_discovery import FileDiscovery
from ..repositories.repo_fetcher import RepoFetcher
from ..storage import MetadataStore
from ..storage.graph_store import Neo4jGraphStore
from ..storage.vector_store import ChromaVectorStore

# Note: This import will be removed when we complete the orchestration pattern
# For now, we import from the legacy location to preserve functionality
from ._legacy_indexer_service import IndexerService

logger = EnhancedLogger(__name__)

ProgressCallback = Callable[[IndexingProgress], None]


class IngestionService:
    """Orchestrates the complete ingestion pipeline using domain modules.

    This service follows the orchestration pattern by:
    - Injecting domain module dependencies through constructor
    - Delegating business logic to domain modules
    - Preserving all existing IndexerService functionality
    - Maintaining backward compatibility
    """

    def __init__(
        self,
        graph_store: Neo4jGraphStore,
        vector_store: ChromaVectorStore,
        metadata_store: MetadataStore,
        embedding_generator: EmbeddingGenerator,
        ingestion_config: Optional[IngestionConfig] = None,
        dual_write_config: Optional[DualWriteConfig] = None,
        # New orchestration dependencies (optional for backward compatibility)
        repo_fetcher: Optional[RepoFetcher] = None,
        file_discovery: Optional[FileDiscovery] = None,
        language_parser: Optional[LanguageParser] = None,
        symbol_extractor: Optional[SymbolExtractor] = None,
        chunker: Optional[Chunker] = None,
    ):
        """Initialize the IngestionService with backward compatibility.

        Args:
            graph_store: Graph storage
            vector_store: Vector storage
            metadata_store: Metadata storage
            embedding_generator: Vector embedding generation
            ingestion_config: Ingestion configuration
            dual_write_config: Dual write configuration
            repo_fetcher: Repository fetching and management (optional)
            file_discovery: File discovery and filtering (optional)
            language_parser: Language detection and AST parsing (optional)
            symbol_extractor: Symbol extraction from AST (optional)
            chunker: Content chunking for embeddings (optional)
        """
        # Store core dependencies (required for backward compatibility)
        self._graph_store = graph_store
        self._vector_store = vector_store
        self._metadata_store = metadata_store
        self._embedding_generator = embedding_generator
        self._ingestion_config = ingestion_config
        self._dual_write_config = dual_write_config

        # Store domain module dependencies (optional for future orchestration)
        self._repo_fetcher = repo_fetcher
        self._file_discovery = file_discovery
        self._language_parser = language_parser
        self._symbol_extractor = symbol_extractor
        self._chunker = chunker

        # For backward compatibility, delegate to existing IndexerService
        # This preserves all existing functionality while we transition
        self._indexer_service = IndexerService(
            graph_store=graph_store,
            vector_store=vector_store,
            metadata_store=metadata_store,
            embedding_generator=embedding_generator,
            ingestion_config=ingestion_config,
            dual_write_config=dual_write_config,
        )

    def index_repo(
        self,
        repo_id: str,
        repo_path: str,
        git_url: str,
        branch: str,
        commit_sha: str,
        progress_callback: Optional[ProgressCallback] = None,
        resume: bool = False,
    ) -> IndexingProgress:
        """Run two-pass indexing pipeline for a repository.

        **PRESERVED**: All existing IndexerService functionality and behavior.
        **PRESERVED**: Two-pass architecture (Pass 1 parallel, Pass 2 sequential).
        **PRESERVED**: Resume capability and progress tracking.

        Args:
            repo_id: Unique repository identifier.
            repo_path: Local path to the repository.
            git_url: Git URL of the repository.
            branch: Branch being indexed.
            commit_sha: Current commit SHA.
            progress_callback: Optional callback for progress updates.
            resume: If True, skip files that have already been indexed.

        Returns:
            IndexingProgress with final status and statistics.
        """
        logger.info(f"IngestionService orchestrating indexing for repo {repo_id}")

        # Delegate to existing IndexerService to preserve all functionality
        return self._indexer_service.index_repo(
            repo_id=repo_id,
            repo_path=repo_path,
            git_url=git_url,
            branch=branch,
            commit_sha=commit_sha,
            progress_callback=progress_callback,
            resume=resume,
        )

    def request_pause(self) -> None:
        """Request the indexing process to pause at the next checkpoint.

        **PRESERVED**: Exact same functionality as IndexerService.
        """
        self._indexer_service.request_pause()

    def clear_pause(self) -> None:
        """Clear the pause request flag.

        **PRESERVED**: Exact same functionality as IndexerService.
        """
        self._indexer_service.clear_pause()

    def is_pause_requested(self) -> bool:
        """Check if a pause has been requested.

        **PRESERVED**: Exact same functionality as IndexerService.

        Returns:
            True if pause has been requested.
        """
        return self._indexer_service.is_pause_requested()

    def get_repo_status(self, repo_id: str) -> Optional[RepoStatus]:
        """Get the current status of a repository.

        **PRESERVED**: Exact same functionality as IndexerService.

        Args:
            repo_id: Repository identifier.

        Returns:
            Current repository status or None if not found.
        """
        return self._indexer_service.get_repo_status(repo_id)

    def is_repo_ready(self, repo_id: str) -> bool:
        """Check if a repository is ready for querying.

        **PRESERVED**: Exact same functionality as IndexerService.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if repository is ready for querying.
        """
        return self._indexer_service.is_repo_ready(repo_id)

    # Future: Implement orchestration methods that delegate to domain modules
    # This will be done in a future phase to gradually migrate away from IndexerService

    def _orchestrate_repository_cloning(self, repo_url: str, branch: str) -> str:
        """Future: Orchestrate repository cloning using RepoFetcher."""
        # TODO: Implement orchestration using self._repo_fetcher
        pass

    def _orchestrate_file_discovery(self, repo_path: str) -> list:
        """Future: Orchestrate file discovery using FileDiscovery."""
        # TODO: Implement orchestration using self._file_discovery
        pass

    def _orchestrate_parsing_and_extraction(
        self, file_path: str, content: str
    ) -> tuple:
        """Future: Orchestrate parsing and symbol extraction."""
        # TODO: Implement orchestration using self._language_parser and self._symbol_extractor
        pass

    def _orchestrate_chunking_and_embedding(self, content: str, symbols: list) -> list:
        """Future: Orchestrate chunking and embedding generation."""
        # TODO: Implement orchestration using self._chunker and self._embedding_generator
        pass

    def _orchestrate_storage(
        self, symbols: list, chunks: list, embeddings: list
    ) -> None:
        """Future: Orchestrate storage using storage classes."""
        # TODO: Implement orchestration using self._graph_store and self._vector_store
        pass


# Backward compatibility alias
IndexerServiceV2 = IngestionService
