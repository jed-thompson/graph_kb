"""Analysis Service V2 for orchestrating code understanding analysis using neo4j-graphrag.

This module provides the AnalysisServiceV2 class that orchestrates all analysis
components using neo4j-graphrag for graph-based retrieval augmented generation.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, List, Optional

from neo4j import Driver

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..adapters.external import EmbedderAdapter, LLMAdapter
from ..adapters.storage import GraphRetrieverAdapter, VectorCypherRetrieverAdapter
from ..models import (
    AnalysisConfig,
    CodeAnalysisResult,
    DataFlow,
    DomainConcept,
    EmbedderNotConfiguredError,
    EntryPoint,
    NarrativeSummary,
)
from ..querying.models import GraphRAGResult
from .analyzers import DataFlowTracerV2, DomainExtractorV2, EntryPointAnalyzerV2
from .builders import ContextPacketBuilderV2, NarrativeGeneratorV2

if TYPE_CHECKING:
    from ..services.query_service import CodeQueryService
    from ..storage import MetadataStore
    from ..storage.neo4j.edge_repository import EdgeRepository
    from ..storage.neo4j.node_repository import NodeRepository
    from ..storage.neo4j.vector_repository import VectorRepository

logger = EnhancedLogger(__name__)


class AnalysisServiceV2:
    """Service for orchestrating code understanding analysis using neo4j-graphrag.

    This service wires together all V2 analyzer components to provide:
    - Entry point discovery
    - Data flow tracing
    - Domain concept extraction
    - Context retrieval using hybrid vector + graph search
    - Narrative summary generation
    - Full comprehensive analysis

    The service uses neo4j-graphrag components for graph-based retrieval
    augmented generation (GraphRAG).
    """

    def __init__(
        self,
        driver: Driver,
        embedder: Optional[Any] = None,
        llm: Optional[Any] = None,
        config: Optional[AnalysisConfig] = None,
        query_service: Optional["CodeQueryService"] = None,
        metadata_store: Optional["MetadataStore"] = None,
        node_repository: Optional["NodeRepository"] = None,
        edge_repository: Optional["EdgeRepository"] = None,
        vector_repository: Optional["VectorRepository"] = None,
    ):
        """Initialize the AnalysisServiceV2 with neo4j-graphrag components.

        Supports two initialization modes:
        1. Repository-based (preferred): Pass node_repository, edge_repository,
           and optionally vector_repository for all database operations.
        2. Driver-based (legacy): Pass driver directly for backward compatibility.

        Args:
            driver: Neo4j driver instance for database connections.
            embedder: Optional embedder instance for vector search.
                     If not provided, vector search will not be available.
                     Can be a BaseEmbeddingGenerator or EmbedderAdapter.
            llm: Optional LLM instance for narrative generation.
                If not provided, narrative generation will use fallback.
            config: Optional AnalysisConfig for service configuration.
            query_service: Optional CodeQueryService for backward
                                 compatibility with existing implementations.
                                 Deprecated: Use metadata_store instead.
            metadata_store: Optional MetadataStore for repository validation.
                           Preferred over query_service.
            node_repository: Optional NodeRepository for node operations.
            edge_repository: Optional EdgeRepository for edge/relationship operations.
            vector_repository: Optional VectorRepository for vector search operations.
        """
        self._driver = driver
        self._embedder = embedder
        self._llm = llm
        self._config = config or AnalysisConfig(
            neo4j_uri="",
            neo4j_user="",
            neo4j_password="",
        )
        self._query_service = query_service
        self._metadata_store = metadata_store

        # Store repository references
        self._node_repository = node_repository
        self._edge_repository = edge_repository
        self._vector_repository = vector_repository

        # Determine if we're using repository-based initialization
        self._use_repositories = (
            node_repository is not None and edge_repository is not None
        )

        # Initialize database name from config
        database = self._config.neo4j_database

        # Initialize adapters based on available components
        self._graph_retriever = self._create_graph_retriever(database)

        # Create embedder adapter if embedder is provided
        self._embedder_adapter: Optional[EmbedderAdapter] = None
        if embedder is not None:
            if isinstance(embedder, EmbedderAdapter):
                self._embedder_adapter = embedder
            else:
                # Wrap raw embedder in adapter
                try:
                    self._embedder_adapter = EmbedderAdapter(embedder)
                except EmbedderNotConfiguredError:
                    logger.warning("Embedder not configured, vector search disabled")

        # Vector retriever requires embedder and repositories
        self._vector_retriever: Optional[VectorCypherRetrieverAdapter] = None
        if self._embedder_adapter is not None:
            self._vector_retriever = self._create_vector_retriever(database)

        # LLM adapter for narrative generation
        self._llm_adapter = LLMAdapter(llm=llm)

        # Initialize analyzers
        self._entry_point_analyzer = EntryPointAnalyzerV2(self._graph_retriever)
        self._data_flow_tracer = DataFlowTracerV2(self._graph_retriever)
        self._domain_extractor = DomainExtractorV2(self._graph_retriever)

        # Initialize builders
        self._context_packet_builder = ContextPacketBuilderV2()
        self._narrative_generator = NarrativeGeneratorV2(self._llm_adapter)

    def _create_graph_retriever(self, database: str) -> GraphRetrieverAdapter:
        """Create GraphRetrieverAdapter using repositories or driver.

        Args:
            database: Neo4j database name.

        Returns:
            Configured GraphRetrieverAdapter instance.
        """
        if self._use_repositories:
            # Repository-based initialization (preferred)
            return GraphRetrieverAdapter(
                self._node_repository,
                self._edge_repository,
                database=database,
            )
        else:
            # Driver-based initialization (legacy/backward compatibility)
            return GraphRetrieverAdapter(self._driver, database)

    def _create_vector_retriever(
        self, database: str
    ) -> Optional[VectorCypherRetrieverAdapter]:
        """Create VectorCypherRetrieverAdapter using repositories or driver.

        Args:
            database: Neo4j database name.

        Returns:
            Configured VectorCypherRetrieverAdapter instance, or None if
            required components are not available.
        """
        if self._embedder_adapter is None:
            return None

        # VectorCypherRetrieverAdapter requires repositories
        if self._vector_repository is not None and self._edge_repository is not None:
            try:
                return VectorCypherRetrieverAdapter(
                    vector_repository=self._vector_repository,
                    edge_repository=self._edge_repository,
                    embedder=self._embedder_adapter,
                    index_name=self._config.vector_index_name,
                    database=database,
                    default_expansion_depth=self._config.default_traversal_depth,
                )
            except EmbedderNotConfiguredError:
                logger.warning("Embedder not configured, vector search disabled")
                return None
        else:
            # Cannot create vector retriever without repositories
            logger.warning(
                "Vector search disabled: VectorCypherRetrieverAdapter requires "
                "vector_repository and edge_repository"
            )
            return None

    @property
    def graph_retriever(self) -> GraphRetrieverAdapter:
        """Get the graph retriever adapter.

        Returns:
            The GraphRetrieverAdapter instance.
        """
        return self._graph_retriever

    @property
    def vector_retriever(self) -> Optional[VectorCypherRetrieverAdapter]:
        """Get the vector retriever adapter.

        Returns:
            The VectorCypherRetrieverAdapter instance, or None if not configured.
        """
        return self._vector_retriever

    @property
    def has_vector_search(self) -> bool:
        """Check if vector search is available.

        Returns:
            True if vector search is configured, False otherwise.
        """
        return self._vector_retriever is not None

    @property
    def has_llm(self) -> bool:
        """Check if LLM is available for narrative generation.

        Returns:
            True if LLM is configured, False otherwise.
        """
        return self._llm_adapter.is_configured

    def analyze_entry_points(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[EntryPoint]:
        """Analyze a repository to discover entry points.

        Entry points are functions, methods, or endpoints that serve as
        external interfaces (API endpoints, CLI commands, main functions,
        event handlers).

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered EntryPoint objects.

        Raises:
            RepositoryNotFoundError: If the repository doesn't exist.
            RepositoryNotReadyError: If the repository is not ready.
        """
        logger.info(f"Analyzing entry points for repository: {repo_id}")

        # Validate repository
        self._query_service.validate_repository(repo_id)

        return self._entry_point_analyzer.analyze(repo_id, folder_path)

    def trace_data_flow(
        self,
        entry_point: EntryPoint,
        max_depth: int = 10,
    ) -> DataFlow:
        """Trace data flow from an entry point.

        Follows the call chain from an entry point through the codebase,
        classifying each step and detecting cycles.

        Args:
            entry_point: The entry point to trace from.
            max_depth: Maximum depth to trace (default 10).

        Returns:
            DataFlow containing the traced steps.
        """
        logger.info(f"Tracing data flow from entry point: {entry_point.name}")
        return self._data_flow_tracer.trace(entry_point, max_depth)

    def extract_domain_concepts(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[DomainConcept]:
        """Extract domain concepts from a repository.

        Domain concepts are classes representing business entities, services,
        repositories, utilities, and value objects.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered DomainConcept objects.

        Raises:
            RepositoryNotFoundError: If the repository doesn't exist.
            RepositoryNotReadyError: If the repository is not ready.
        """
        logger.info(f"Extracting domain concepts for repository: {repo_id}")

        # Validate repository
        self._query_service.validate_repository(repo_id)

        return self._domain_extractor.extract(repo_id, folder_path)

    def retrieve_context(
        self,
        repo_id: str,
        query: str,
        max_depth: int = 5,
        max_expansion_nodes: int = 500,
        top_k: int = 30,
        include_visualization: bool = True,
    ) -> GraphRAGResult:
        """Retrieve context using hybrid vector + graph search.

        Uses VectorCypherRetriever to find semantically similar code symbols
        and expand their graph neighborhoods.

        Args:
            repo_id: The repository ID to search.
            query: Natural language query for semantic search.
            max_depth: Maximum depth for graph expansion (default 5).
            max_expansion_nodes: Maximum nodes to return per symbol expansion (default 500).
            top_k: Maximum number of initial vector search results (default 30).
            include_visualization: Whether to generate a Mermaid diagram (default True).

        Returns:
            GraphRAGResult containing context packets, visualization, and metadata.

        Raises:
            EmbedderNotConfiguredError: If vector search is not configured.
        """
        logger.info(f"Retrieving context for query: {query[:50]}...")

        if self._vector_retriever is None:
            raise EmbedderNotConfiguredError(
                "Vector search is not configured. Provide an embedder to enable."
            )

        return self._vector_retriever.search_with_context(
            query=query,
            repo_id=repo_id,
            top_k=top_k,
            expansion_depth=max_depth,
            max_expansion_nodes=max_expansion_nodes,
            include_visualization=include_visualization,
        )

    async def generate_narrative(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> NarrativeSummary:
        """Generate a narrative summary for a repository.

        This method first discovers entry points and domain concepts,
        then uses LLM to generate a human-readable narrative.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            A NarrativeSummary containing the generated narrative.

        Raises:
            RepositoryNotFoundError: If the repository doesn't exist.
            RepositoryNotReadyError: If the repository is not ready.
        """
        logger.info(f"Generating narrative for repository: {repo_id}")

        # Get entry points and domain concepts for narrative generation
        entry_points = self.analyze_entry_points(repo_id, folder_path)
        domain_concepts = self.extract_domain_concepts(repo_id, folder_path)

        # Generate narrative using LLM
        return await self._narrative_generator.generate(
            repo_id=repo_id,
            entry_points=entry_points,
            domain_concepts=domain_concepts,
        )

    async def full_analysis(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
        include_data_flows: bool = True,
        max_flow_depth: int = 5,
        include_narrative: bool = True,
    ) -> CodeAnalysisResult:
        """Perform a full comprehensive analysis of a repository.

        This method orchestrates all analysis components to provide:
        - Entry point discovery
        - Domain concept extraction
        - Narrative summary generation (optional, may fail gracefully)

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.
            include_data_flows: Whether to include data flow tracing (default True, currently unused).
            max_flow_depth: Maximum depth for data flow tracing (unused).
            include_narrative: Whether to include narrative generation (default True).

        Returns:
            CodeAnalysisResult containing all analysis results.

        Raises:
            RepositoryNotFoundError: If the repository doesn't exist.
            RepositoryNotReadyError: If the repository is not ready.
        """
        logger.info(f"Starting full analysis for repository: {repo_id}")

        # Validate repository
        self._query_service.validate_repository(repo_id)

        # Analyze entry points
        logger.info("Analyzing entry points...")
        entry_points: List[EntryPoint] = []
        try:
            entry_points = self._entry_point_analyzer.analyze(repo_id, folder_path)
            logger.info(f"Found {len(entry_points)} entry points")
        except Exception as e:
            logger.warning(
                f"Entry point analysis failed: {e}. Continuing with partial results."
            )

        # Extract domain concepts
        logger.info("Extracting domain concepts...")
        domain_concepts: List[DomainConcept] = []
        try:
            domain_concepts = self._domain_extractor.extract(repo_id, folder_path)
            logger.info(f"Found {len(domain_concepts)} domain concepts")
        except Exception as e:
            logger.warning(
                f"Domain concept extraction failed: {e}. Continuing with partial results."
            )

        # Generate narrative (optional, handle errors gracefully)
        narrative: Optional[NarrativeSummary] = None
        if include_narrative:
            logger.info("Generating narrative summary...")
            try:
                narrative = await self._narrative_generator.generate(
                    repo_id=repo_id,
                    entry_points=entry_points,
                    domain_concepts=domain_concepts,
                )
                logger.info("Narrative generation complete")
            except Exception as e:
                logger.warning(
                    f"Narrative generation failed: {e}. Continuing with partial results."
                )
                narrative = None

        # Build and return the complete result
        return CodeAnalysisResult(
            repo_id=repo_id,
            entry_points=entry_points,
            domain_concepts=domain_concepts,
            narrative=narrative,
            generated_at=datetime.now(UTC),
        )

    def set_query_service(self, query_service: "CodeQueryService") -> None:
        """Set the legacy query service for backward compatibility.

        Args:
            query_service: The CodeQueryService instance to use.
        """
        self._query_service = query_service

    def set_metadata_store(self, metadata_store: "MetadataStore") -> None:
        """Set the metadata store for repository validation.

        Args:
            metadata_store: The MetadataStore instance to use.
        """
        self._metadata_store = metadata_store
