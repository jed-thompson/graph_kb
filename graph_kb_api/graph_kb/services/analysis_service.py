"""Code Analysis Service for entry points, data flow, and domain extraction.

This service consolidates AnalysisServiceV2 functionality, providing
code analysis capabilities. It accesses storage only through adapters.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis.analyzers.data_flow import DataFlowTracerV2 as DataFlowTracer
from ..analysis.analyzers.domain import DomainExtractorV2 as DomainExtractor
from ..analysis.analyzers.entry_point import EntryPointAnalyzerV2 as EntryPointAnalyzer
from ..analysis.builders.narrative import NarrativeGeneratorV2 as NarrativeGenerator
from ..models.analysis import (
    CodeAnalysisResult,
    DataFlow,
    DomainConcept,
    EntryPoint,
    NarrativeSummary,
)
from ..querying.models import GraphRAGResult
from ..storage import MetadataStore
from .base_service import BaseGraphKBService

if TYPE_CHECKING:
    from ..adapters.external.llm_adapter import LLMAdapter
    from ..adapters.storage.graph_retriever import GraphRetrieverAdapter
    from ..adapters.storage.vector_cypher_retriever import VectorCypherRetrieverAdapter

logger = EnhancedLogger(__name__)


class CodeAnalysisService(BaseGraphKBService):
    """Service for high-level code analysis and insights.

    **Purpose**: Discover architectural patterns, trace execution flows, extract
    domain concepts, and generate human-readable narratives about code structure.

    **Use this service when**:
    - You need to discover entry points (main functions, API endpoints, CLI commands)
    - You want to trace data flow through the system
    - You need to extract domain concepts and business logic patterns
    - You want LLM-generated narrative summaries of code architecture
    - You're performing comprehensive code analysis

    **Key capabilities**:
    - Entry point discovery (finds main(), API routes, CLI commands)
    - Data flow tracing (follows execution paths from entry points)
    - Domain concept extraction (identifies business entities and patterns)
    - Narrative generation (LLM-powered summaries)
    - Full comprehensive analysis (combines all analysis types)

    **Contrast with other services**:
    - CodeQueryService: Low-level graph queries (what calls what)
    - CodeRetrievalService: Semantic search for relevant code
    - CodeAnalysisService: High-level insights and architectural understanding

    **Example**:
        >>> # Discover all entry points in a repository
        >>> entry_points = service.analyze_entry_points("my-repo")
        >>> # Returns: [EntryPoint(name="main", type="function", ...)]
        >>>
        >>> # Trace data flow from an entry point
        >>> flow = service.trace_data_flow(entry_points[0], max_depth=10)
        >>>
        >>> # Extract domain concepts
        >>> concepts = service.extract_domain_concepts("my-repo")
        >>> # Returns: [DomainConcept(name="User", type="entity", ...)]
        >>>
        >>> # Generate narrative summary
        >>> narrative = await service.generate_narrative("my-repo")
        >>> print(narrative.summary)  # Human-readable architecture description

    The service accesses storage only through adapters, following the
    architecture: Services → Adapters → Facade → Repositories
    """

    def __init__(
        self,
        graph_retriever: "GraphRetrieverAdapter",
        vector_adapter: Optional["VectorCypherRetrieverAdapter"] = None,
        llm_adapter: Optional["LLMAdapter"] = None,
        metadata_store: Optional[MetadataStore] = None,
    ):
        """Initialize the CodeAnalysisService.

        Args:
            graph_retriever: Adapter for graph retrieval operations.
            vector_adapter: Optional adapter for vector operations.
            llm_adapter: Optional adapter for LLM operations.
            metadata_store: Optional metadata store for repository info.
        """
        super().__init__(metadata_store)
        self._graph_retriever = graph_retriever
        self._vector_adapter = vector_adapter

        # Initialize analyzers
        self._entry_point_analyzer = EntryPointAnalyzer(retriever=graph_retriever)
        self._data_flow_tracer = DataFlowTracer(retriever=graph_retriever)
        self._domain_extractor = DomainExtractor(retriever=graph_retriever)

        # Initialize narrative generator with LLM adapter
        if llm_adapter:
            self._narrative_generator = NarrativeGenerator(llm_adapter=llm_adapter)
        else:
            # Create default LLM adapter
            try:
                from ..adapters.external.llm_adapter import LLMAdapter

                self._narrative_generator = NarrativeGenerator(
                    llm_adapter=LLMAdapter(llm=None)
                )
            except ImportError:
                # Fallback if adapters not available yet
                self._narrative_generator = NarrativeGenerator()

    @property
    def has_vector_search(self) -> bool:
        """Check if vector search is available.

        Returns:
            True if vector adapter is configured, False otherwise.
        """
        return self._vector_adapter is not None

    @property
    def has_llm(self) -> bool:
        """Check if LLM is available for narrative generation.

        Returns:
            True if LLM adapter is configured, False otherwise.
        """
        return (
            hasattr(self._narrative_generator, "_llm_adapter")
            and self._narrative_generator._llm_adapter is not None
        )

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

        Uses VectorCypherRetrieverAdapter to find semantically similar code symbols
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
        from ..models import EmbedderNotConfiguredError

        if self._vector_adapter is None:
            raise EmbedderNotConfiguredError(
                "Vector search is not configured. Provide a vector_adapter to enable."
            )

        return self._vector_adapter.search_with_context(
            query=query,
            repo_id=repo_id,
            top_k=top_k,
            expansion_depth=max_depth,
            max_expansion_nodes=max_expansion_nodes,
            include_visualization=include_visualization,
        )

    def analyze_entry_points(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[EntryPoint]:
        """Analyze a repository to discover entry points.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered EntryPoint objects.
        """
        logger.info(f"Analyzing entry points for repository: {repo_id}")
        return self._entry_point_analyzer.analyze(repo_id, folder_path)

    def trace_data_flow(
        self,
        entry_point: EntryPoint,
        max_depth: int = 10,
    ) -> DataFlow:
        """Trace data flow from an entry point.

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

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered DomainConcept objects.
        """
        logger.info(f"Extracting domain concepts for repository: {repo_id}")
        return self._domain_extractor.extract(repo_id, folder_path)

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
        """
        logger.info(f"Generating narrative for repository: {repo_id}")

        # Get entry points and domain concepts
        entry_points = self._entry_point_analyzer.analyze(repo_id, folder_path)
        domain_concepts = self._domain_extractor.extract(repo_id, folder_path)

        # Generate narrative using LLM
        return await self._narrative_generator.generate(
            repo_id=repo_id,
            entry_points=entry_points,
            domain_concepts=domain_concepts,
            folder_path=folder_path,
        )

    async def full_analysis(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
        include_data_flows: bool = True,
        include_narrative: bool = True,
        max_flow_depth: int = 10,
    ) -> CodeAnalysisResult:
        """Perform full comprehensive analysis of a repository.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.
            include_data_flows: Whether to trace data flows (default True).
            include_narrative: Whether to generate narrative (default True).
            max_flow_depth: Maximum depth for data flow tracing (default 10).

        Returns:
            CodeAnalysisResult containing all analysis results.
        """
        logger.info(f"Starting full analysis for repository: {repo_id}")

        # Step 1: Discover entry points
        entry_points = self._entry_point_analyzer.analyze(repo_id, folder_path)
        logger.info(f"Discovered {len(entry_points)} entry points")

        # Step 2: Trace data flows (optional)
        data_flows = []
        if include_data_flows:
            for entry_point in entry_points:
                try:
                    flow = self._data_flow_tracer.trace(entry_point, max_flow_depth)
                    data_flows.append(flow)
                except Exception as e:
                    logger.warning(
                        f"Failed to trace data flow for {entry_point.name}: {e}"
                    )

        # Step 3: Extract domain concepts
        domain_concepts = self._domain_extractor.extract(repo_id, folder_path)
        logger.info(f"Extracted {len(domain_concepts)} domain concepts")

        # Step 4: Generate narrative (optional)
        narrative = None
        if include_narrative:
            try:
                narrative = await self._narrative_generator.generate(
                    repo_id=repo_id,
                    entry_points=entry_points,
                    domain_concepts=domain_concepts,
                    folder_path=folder_path,
                )
            except Exception as e:
                logger.warning(f"Failed to generate narrative: {e}")

        return CodeAnalysisResult(
            repo_id=repo_id,
            entry_points=entry_points,
            domain_concepts=domain_concepts,
            generated_at=datetime.now(),
            narrative=narrative,
        )

    def resolve_symbol_id(self, repo_id: str, symbol: str) -> Optional[str]:
        """Resolve a symbol name to its ID in the graph.

        **PRESERVED**: Method from GraphQueryService interface.

        Args:
            repo_id: Repository identifier.
            symbol: Symbol name to resolve.

        Returns:
            Symbol ID if found, None otherwise.
        """
        # Delegate to graph retriever if available
        if hasattr(self._graph_retriever, "resolve_symbol_id"):
            return self._graph_retriever.resolve_symbol_id(repo_id, symbol)

        # Fallback implementation
        logger.warning(f"Symbol resolution not fully implemented for {symbol}")
        return None

    def get_architecture(self, repo_id: str) -> dict:
        """Get architecture overview for a repository.

        **PRESERVED**: Method from GraphQueryService interface.

        Args:
            repo_id: Repository identifier.

        Returns:
            Dictionary containing architecture information.
        """
        # Use existing analysis methods to build architecture overview
        entry_points = self.analyze_entry_points(repo_id)
        domain_concepts = self.extract_domain_concepts(repo_id)

        return {
            "repo_id": repo_id,
            "entry_points": [
                {
                    "name": ep.name,
                    "type": ep.type.value
                    if hasattr(ep.type, "value")
                    else str(ep.type),
                    "file_path": ep.file_path,
                }
                for ep in entry_points
            ],
            "domain_concepts": [
                {
                    "name": dc.name,
                    "type": dc.type.value
                    if hasattr(dc.type, "value")
                    else str(dc.type),
                    "description": dc.description,
                }
                for dc in domain_concepts
            ],
            "total_entry_points": len(entry_points),
            "total_domain_concepts": len(domain_concepts),
        }
