"""Unified facade for Graph KB subsystem.

This module provides a facade that manages the lifecycle and dependencies
of all Graph KB components: storage, adapters, services, and tools.

The facade follows a strict initialization order:
1. Storage layer (graph_store, vector_store, metadata_store)
2. Adapters (traversal, symbol_query, stats, visualization)
3. Services (query, retrieval, analysis, visualization)
4. Tools (tool registry with all available tools)

Usage:
    >>> from graph_kb_api.graph_kb import get_facade
    >>> facade = get_facade()
    >>> # Access services
    >>> result = facade.query_service.resolve_symbol_id("my-repo", "MyClass")
    >>> # Create agent
    >>> agent = facade.create_agent(llm)
"""

from typing import Optional

from langchain_core.language_models import BaseChatModel

from graph_kb_api.config import settings
from graph_kb_api.database.metadata_service import (
    AsyncMetadataService,
    SyncMetadataService,
)
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

# Import adapters at top level - no circular import issues found
from .adapters.storage import (
    GraphRetrieverAdapter,
    GraphStatsAdapter,
    SymbolQueryAdapter,
    TraversalAdapter,
    VectorCypherRetrieverAdapter,
)
from .agent.code_agent import CodeAgent
from .config import ChromaConfig, DualWriteConfig, Neo4jConfig

# Import processing classes for runtime use
from .processing.embedding_generator import (
    EmbeddingGenerator as BaseEmbeddingGenerator,
)
from .processing.embedding_generator import (
    LocalEmbeddingGenerator,
)
from .processing.embedding_generator import (
    OpenAIEmbeddingGenerator as EmbeddingGenerator,
)
from .prompts.prompt_manager import GraphKBPromptManager
from .repositories.repo_fetcher import GitRepoFetcher
from .services.analysis_service import CodeAnalysisService
from .services.code_visualization_service import CodeVisualizationService
from .services.ingestion_service import IngestionService

# Import services at top level - no circular import issues found
from .services.query_service import CodeQueryService
from .services.retrieval_service import CodeRetrievalService

# Import storage classes for runtime use
from .storage.graph_store import Neo4jGraphStore
from .storage.vector_store import ChromaVectorStore

# Import tools at top level
from .tools import ToolRegistry, create_tool_registry
from .visualization.querier import GraphQuerier

logger = EnhancedLogger(__name__)


class GraphKBFacade:
    """Unified facade for the Graph KB subsystem.

    This singleton provides a simplified interface to the entire Graph KB system:
    - Storage layer (graph_store, vector_store, metadata_store)
    - Adapters (traversal, symbol_query, stats, visualization)
    - Services (query, retrieval, analysis, visualization)
    - Tool registry
    - Agent factory

    The facade ensures proper initialization order and dependency injection,
    following the architecture:
    Commands → Tools → Services → Adapters → Facade → Repositories

    Example:
        >>> facade = GraphKBFacade.get_instance()
        >>> facade.initialize()
        >>>
        >>> # Use services
        >>> symbols = facade.query_service.get_symbols_by_pattern("my-repo")
        >>>
        >>> # Create agent
        >>> agent = facade.create_agent(llm)

    The singleton pattern ensures all commands and tools share the same
    service instances, avoiding duplicate initialization and resource usage.
    """

    _instance: Optional["GraphKBFacade"] = None

    def __init__(self):
        """Initialize the facade (private - use get_instance())."""
        # Storage layer
        self._graph_store: Optional["Neo4jGraphStore"] = None
        self._vector_store: Optional["ChromaVectorStore"] = None
        self._metadata_store: Optional["SyncMetadataService"] = None
        self._embedding_generator: Optional["BaseEmbeddingGenerator"] = None
        self._repo_fetcher: Optional["GitRepoFetcher"] = None

        # Adapters (services access storage through these)
        self._traversal_adapter: Optional["TraversalAdapter"] = None
        self._symbol_query_adapter: Optional["SymbolQueryAdapter"] = None
        self._stats_adapter: Optional["GraphStatsAdapter"] = None
        self._graph_querier: Optional["GraphQuerier"] = None
        self._graph_retriever_adapter: Optional["GraphRetrieverAdapter"] = None
        self._vector_cypher_adapter: Optional["VectorCypherRetrieverAdapter"] = None

        # Services
        self._query_service: Optional["CodeQueryService"] = None
        self._retrieval_service: Optional["CodeRetrievalService"] = None
        self._analysis_service: Optional["CodeAnalysisService"] = None
        self._visualization_service: Optional["CodeVisualizationService"] = None
        self._ingestion_service: Optional["IngestionService"] = None

        # Prompt manager
        self._prompt_manager: Optional["GraphKBPromptManager"] = None

        # Tools
        self._tool_registry: Optional["ToolRegistry"] = None

        # Initialization flag
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the facade has been initialized."""
        return self._initialized

    @classmethod
    def get_instance(cls) -> "GraphKBFacade":
        """Get or create the singleton instance.

        Returns:
            The singleton GraphKBFacade instance.
        """
        if cls._instance is None:
            cls._instance = cls()
            logger.debug("Created new GraphKBFacade singleton instance")
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for testing).

        This method clears the singleton instance, allowing a fresh
        initialization. Use with caution in production code.
        """
        if cls._instance is not None:
            logger.debug("Resetting GraphKBFacade singleton instance")
            cls._instance = None

    def initialize(self) -> bool:
        """Initialize all services. Idempotent.

        This method initializes the entire service stack in the correct order:
        1. Storage layer
        2. Adapters
        3. Services
        4. Tools

        The method is idempotent - calling it multiple times has no effect
        after the first successful initialization.

        Returns:
            True if initialization succeeded (or was already complete),
            False if initialization failed.
        """
        if self._initialized:
            logger.debug("GraphKBFacade already initialized, skipping")
            return True

        try:
            logger.info("Initializing GraphKBFacade...")

            # 1. Initialize storage layer
            self._initialize_storage()
            logger.debug("Storage layer initialized")

            # 2. Initialize adapters (depend on storage)
            self._initialize_adapters()
            logger.debug("Adapters initialized")

            # 3. Initialize services (depend on adapters)
            self._initialize_services()
            logger.debug("Services initialized")

            # 4. Initialize tools (depend on services)
            self._initialize_tools()
            logger.debug("Tools initialized")

            self._initialized = True
            logger.info("GraphKBFacade initialization complete")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GraphKBFacade: {e}", exc_info=True)
            return False

    def _initialize_storage(self):
        """Initialize storage layer components."""

        # Initialize configs
        neo4j_config = Neo4jConfig.from_env()
        chroma_config = ChromaConfig.from_env()

        # Initialize graph store and verify connectivity
        self._graph_store = Neo4jGraphStore(config=neo4j_config)
        try:
            if self._graph_store.health_check():
                logger.info("Neo4j connection verified at %s", neo4j_config.uri)
            else:
                logger.error(
                    "Neo4j health check returned unhealthy at %s", neo4j_config.uri
                )
        except Exception as e:
            logger.error(
                "Failed to connect to Neo4j at %s: %s",
                neo4j_config.uri,
                e,
                exc_info=True,
            )

        # Initialize vector store
        self._vector_store = ChromaVectorStore(config=chroma_config)

        # Initialize metadata store (PostgreSQL via async service + sync wrapper)
        from graph_kb_api.database.base import get_session_maker

        session_factory = get_session_maker()
        async_metadata = AsyncMetadataService(session_factory)
        self._metadata_store = SyncMetadataService(async_metadata)
        self._async_metadata_store = async_metadata

        # Initialize repo fetcher
        self._repo_fetcher = GitRepoFetcher(storage_path=settings.graph_kb_repo_path)

        # Initialize embedding generator based on settings
        if settings.embedding_model.startswith("text-embedding"):
            self._embedding_generator = EmbeddingGenerator(
                model=settings.embedding_model
            )
        else:
            self._embedding_generator = LocalEmbeddingGenerator(
                model_name=settings.embedding_model,
                device=settings.embedding_device,
            )

    def _initialize_adapters(self):
        """Initialize adapters that services will use."""

        if not self._graph_store:
            raise RuntimeError("Graph store not initialized")
        if not self._vector_store:
            raise RuntimeError("Vector store not initialized")
        if not self._metadata_store:
            raise RuntimeError("Metadata store not initialized")

        # Storage adapters - use repository-based initialization from graph_store
        self._traversal_adapter = TraversalAdapter(
            self._graph_store.node_repository, self._graph_store.edge_repository
        )
        self._symbol_query_adapter = SymbolQueryAdapter(self._graph_store)
        self._stats_adapter = GraphStatsAdapter(self._graph_store)

        # Visualization adapter
        self._graph_querier = GraphQuerier(self._graph_store)

        # Analysis adapters - initialize GraphRetrieverAdapter using repositories from graph_store
        neo4j_config = Neo4jConfig.from_env()
        self._graph_retriever_adapter = GraphRetrieverAdapter(
            self._graph_store.node_repository,
            self._graph_store.edge_repository,
            database=neo4j_config.database,
        )

        # VectorCypherRetrieverAdapter requires embedder and repositories
        # Initialize if embedding generator is available
        if self._embedding_generator:
            try:
                from .adapters.external import EmbedderAdapter
                from .adapters.storage import VectorCypherRetrieverAdapter

                # Create embedder adapter
                embedder_adapter = EmbedderAdapter(self._embedding_generator)

                # Initialize VectorCypherRetrieverAdapter with repositories
                self._vector_cypher_adapter = VectorCypherRetrieverAdapter(
                    vector_repository=self._graph_store.vector_repository,
                    edge_repository=self._graph_store.edge_repository,
                    embedder=embedder_adapter,
                    database=neo4j_config.database,
                )
                logger.debug("VectorCypherRetrieverAdapter initialized")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize VectorCypherRetrieverAdapter: {e}",
                    exc_info=True,
                )
                self._vector_cypher_adapter = None
        else:
            # No embedding generator available
            self._vector_cypher_adapter = None
            logger.debug(
                "VectorCypherRetrieverAdapter not initialized: no embedding generator"
            )

    def _initialize_services(self):
        """Initialize services (depend on adapters)."""

        if not all(
            [
                self._symbol_query_adapter,
                self._traversal_adapter,
                self._metadata_store,
                self._graph_store,
                self._vector_store,
                self._graph_retriever_adapter,
            ]
        ):
            raise RuntimeError("Required adapters or stores not initialized")

        # Type assertions for type checker (we've verified these are not None above)
        assert self._symbol_query_adapter is not None
        assert self._traversal_adapter is not None
        assert self._metadata_store is not None
        assert self._graph_store is not None
        assert self._vector_store is not None
        assert self._graph_retriever_adapter is not None

        # Query service
        self._query_service = CodeQueryService(
            symbol_adapter=self._symbol_query_adapter,
            traversal_adapter=self._traversal_adapter,
            metadata_store=self._metadata_store,
            stats_adapter=self._stats_adapter,
        )

        # Retrieval service (requires vector_store and embedding_generator)
        if not self._embedding_generator:
            logger.warning(
                "Embedding generator not available, retrieval service may have limited functionality"
            )
            raise RuntimeError("Embedding generator is required for retrieval service")
        assert self._embedding_generator is not None
        self._retrieval_service = CodeRetrievalService(
            symbol_adapter=self._symbol_query_adapter,
            traversal_adapter=self._traversal_adapter,
            vector_store=self._vector_store,
            embedding_generator=self._embedding_generator,
        )

        # Analysis service (graph_retriever is required, vector_adapter is optional)
        self._analysis_service = CodeAnalysisService(
            graph_retriever=self._graph_retriever_adapter,
            vector_adapter=self._vector_cypher_adapter,
            metadata_store=self._metadata_store,
        )

        # Visualization service (requires graph_querier and stats_adapter)
        if not all([self._graph_querier, self._stats_adapter]):
            raise RuntimeError("Visualization adapters not initialized")
        assert self._graph_querier is not None
        assert self._stats_adapter is not None
        self._visualization_service = CodeVisualizationService(
            graph_querier=self._graph_querier,
            stats_adapter=self._stats_adapter,
            metadata_store=self._metadata_store,
        )

        # Ingestion service (requires core storage components)
        if not all(
            [
                self._graph_store,
                self._vector_store,
                self._metadata_store,
                self._embedding_generator,
            ]
        ):
            raise RuntimeError(
                "Core storage components not initialized for ingestion service"
            )
        assert self._graph_store is not None
        assert self._vector_store is not None
        assert self._metadata_store is not None
        assert self._embedding_generator is not None

        # Load dual write config from environment to ensure correct embedding dimensions
        dual_write_config = DualWriteConfig.from_env()

        self._ingestion_service = IngestionService(
            graph_store=self._graph_store,
            vector_store=self._vector_store,
            metadata_store=self._metadata_store,
            embedding_generator=self._embedding_generator,
            dual_write_config=dual_write_config,
        )

        # Prompt manager
        self._prompt_manager = GraphKBPromptManager()

    def _initialize_tools(self):
        """Initialize tools (depend on services)."""

        if not all(
            [
                self._query_service,
                self._retrieval_service,
                self._visualization_service,
                self._graph_retriever_adapter,
            ]
        ):
            raise RuntimeError("Services not initialized")

        # Type assertions for type checker
        assert self._query_service is not None
        assert self._retrieval_service is not None
        assert self._visualization_service is not None
        assert self._graph_retriever_adapter is not None

        # Create tool registry with new consolidated services
        self._tool_registry = create_tool_registry(
            query_service=self._query_service,
            retrieval_service=self._retrieval_service,
            visualization_service=self._visualization_service,
            analysis_service=self._analysis_service,
            retriever_adapter=self._graph_retriever_adapter,
        )

    # =========================================================================
    # Storage Layer Properties
    # =========================================================================

    @property
    def graph_store(self) -> Optional[Neo4jGraphStore]:
        """Get the Neo4j graph store.

        Returns:
            The Neo4jGraphStore instance, or None if not initialized.
        """
        return self._graph_store

    @property
    def vector_store(self) -> Optional[ChromaVectorStore]:
        """Get the Chroma vector store.

        Returns:
            The ChromaVectorStore instance, or None if not initialized.
        """
        return self._vector_store

    @property
    def metadata_store(self) -> Optional[SyncMetadataService]:
        """Get the metadata store (sync wrapper over PostgreSQL).

        Returns:
            The SyncMetadataService instance, or None if not initialized.
        """
        return self._metadata_store

    @property
    def async_metadata_store(self) -> Optional[AsyncMetadataService]:
        """Get the async metadata store for use in async contexts.

        Returns:
            The AsyncMetadataService instance, or None if not initialized.
        """
        return getattr(self, "_async_metadata_store", None)

    @property
    def repo_fetcher(self) -> Optional["GitRepoFetcher"]:
        """Get the repository fetcher.

        Returns:
            The RepoFetcher instance, or None if not initialized.
        """
        return self._repo_fetcher

    @property
    def embedding_generator(self) -> Optional[BaseEmbeddingGenerator]:
        """Get the embedding generator.

        Returns:
            The BaseEmbeddingGenerator instance, or None if not initialized.
        """
        return self._embedding_generator

    # =========================================================================
    # Adapter Layer Properties
    # =========================================================================

    @property
    def traversal_adapter(self) -> Optional[TraversalAdapter]:
        """Get the traversal adapter.

        Returns:
            The TraversalAdapter instance, or None if not initialized.
        """
        return self._traversal_adapter

    @property
    def symbol_query_adapter(self) -> Optional[SymbolQueryAdapter]:
        """Get the symbol query adapter.

        Returns:
            The SymbolQueryAdapter instance, or None if not initialized.
        """
        return self._symbol_query_adapter

    @property
    def stats_adapter(self) -> Optional[GraphStatsAdapter]:
        """Get the graph stats adapter.

        Returns:
            The GraphStatsAdapter instance, or None if not initialized.
        """
        return self._stats_adapter

    @property
    def graph_querier(self) -> Optional[GraphQuerier]:
        """Get the graph querier for visualization.

        Returns:
            The GraphQuerier instance, or None if not initialized.
        """
        return self._graph_querier

    @property
    def graph_retriever_adapter(self) -> Optional[GraphRetrieverAdapter]:
        """Get the graph retriever adapter.

        Returns:
            The GraphRetrieverAdapter instance, or None if not initialized.
        """
        return self._graph_retriever_adapter

    @property
    def vector_cypher_adapter(self) -> Optional[VectorCypherRetrieverAdapter]:
        """Get the vector cypher retriever adapter.

        Returns:
            The VectorCypherRetrieverAdapter instance, or None if not initialized.
        """
        return self._vector_cypher_adapter

    # =========================================================================
    # Service Layer Properties
    # =========================================================================

    @property
    def query_service(self) -> Optional[CodeQueryService]:
        """Get the code query service.

        Returns:
            The CodeQueryService instance, or None if not initialized.
        """
        return self._query_service

    @property
    def retrieval_service(self) -> Optional[CodeRetrievalService]:
        """Get the code retrieval service.

        Returns:
            The CodeRetrievalService instance, or None if not initialized.
        """
        return self._retrieval_service

    @property
    def analysis_service(self) -> Optional[CodeAnalysisService]:
        """Get the code analysis service.

        Returns:
            The CodeAnalysisService instance, or None if not initialized.
        """
        return self._analysis_service

    @property
    def visualization_service(self) -> Optional[CodeVisualizationService]:
        """Get the code visualization service.

        Returns:
            The CodeVisualizationService instance, or None if not initialized.
        """
        return self._visualization_service

    @property
    def ingestion_service(self) -> Optional[IngestionService]:
        """Get the ingestion service.

        Returns:
            The IngestionService instance, or None if not initialized.
        """
        return self._ingestion_service

    @property
    def prompt_manager(self) -> Optional[GraphKBPromptManager]:
        """Get the prompt manager.

        Returns:
            The GraphKBPromptManager instance, or None if not initialized.
        """
        return self._prompt_manager

    # =========================================================================
    # Tool Layer Properties
    # =========================================================================

    @property
    def tool_registry(self) -> Optional["ToolRegistry"]:
        """Get the tool registry.

        Returns:
            The ToolRegistry instance, or None if not initialized.
        """
        return self._tool_registry

    # =========================================================================
    # Agent Factory
    # =========================================================================

    def create_agent(
        self,
        llm: "BaseChatModel",
        system_prompt: Optional[str] = None,
    ) -> Optional[CodeAgent]:
        """Create a CodeAgent with the shared tool registry.

        Args:
            llm: The language model to use for the agent.
            system_prompt: Optional custom system prompt.

        Returns:
            A configured CodeAgent instance, or None if tool registry
            is not initialized.
        """
        if not self._tool_registry:
            logger.error("Cannot create agent: tool registry not initialized")
            return None

        try:
            from .agent.code_agent import CodeAgent

            # Use default prompt if none provided
            if system_prompt is None:
                system_prompt = (
                    "You are a helpful code assistant with access to Graph KB tools."
                )

            agent = CodeAgent(
                llm=llm,
                tool_registry=self._tool_registry,
                system_prompt=system_prompt,
                max_iterations=20,
            )

            logger.info("Created CodeAgent with shared tool registry")
            return agent

        except Exception as e:
            logger.error(f"Failed to create CodeAgent: {e}", exc_info=True)
            return None

    def create_code_agent(
        self,
        llm: BaseChatModel,
        system_prompt: Optional[str] = None,
    ) -> Optional[CodeAgent]:
        """Create a CodeAgent with the shared tool registry.

        .. deprecated:: 2.0
            Use create_agent instead. This method is provided for
            backward compatibility only.

        Args:
            llm: The language model to use for the agent.
            system_prompt: Optional custom system prompt.

        Returns:
            A configured CodeAgent instance, or None if tool registry
            is not initialized.
        """
        return self.create_agent(llm, system_prompt)


def get_facade() -> GraphKBFacade:
    """Get initialized Graph KB facade.

    This is the main entry point for accessing the Graph KB subsystem.
    It returns a singleton instance that is automatically initialized.

    Returns:
        An initialized GraphKBFacade instance.

    Raises:
        RuntimeError: If facade initialization fails.

    Example:
        >>> from graph_kb_api.graph_kb import get_facade
        >>> facade = get_facade()
        >>> result = facade.query_service.resolve_symbol_id("my-repo", "MyClass")
    """
    facade = GraphKBFacade.get_instance()
    if not facade.initialize():
        raise RuntimeError(
            "Failed to initialize GraphKBFacade. Check logs for details. "
            "Ensure Neo4j and ChromaDB are running and properly configured."
        )
    return facade
