"""
Type definitions for LangGraph v3 workflows.

This module provides TypedDict definitions for structured data used
throughout the workflow system, ensuring type safety and better IDE support.

Note: While LangGraph uses `RunnableConfig` as the primary type, we provide
`ThreadConfig` as a more specific TypedDict for better type hints and IDE
support when working with our workflow configurations.

## Usage Examples

### Creating a thread configuration with services:

```python
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.config import create_thread_config
from graph_kb_api.context import AppContext

# Create service registry
services: ServiceRegistry = {
    'app_context': app_context,
    'messenger': messenger,
}

# Create thread config (returns RunnableConfig)
config = create_thread_config(
    user_id="user123",
    session_id="session456",
    repo_id="my-repo",
    services=services
)
```

### Accessing services in workflow nodes:

```python
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.models import ServiceRegistry

class MyNode(BaseWorkflowNodeV3):
    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: ServiceRegistry
    ) -> NodeExecutionResult:
        # Type-safe service access
        app_context = services.get('app_context')
        if not app_context:
            return NodeExecutionResult.error("App context not available")

        # Use services...
        result = await app_context.llm.a_generate_response(prompt)
        return NodeExecutionResult.success(output={'result': result})
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, NotRequired, Optional, TypedDict

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
    from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
    from graph_kb_api.flows.v3.state.plan_state import ProgressEvent
    from graph_kb_api.graph_kb.facade import GraphKBFacade
    from graph_kb_api.storage.blob_storage import BlobStorage

from graph_kb_api.context import AppContext
from graph_kb_api.graph_kb.processing.embedding_generator import EmbeddingGenerator
from graph_kb_api.graph_kb.repositories.file_discovery import FileSystemDiscovery
from graph_kb_api.graph_kb.repositories.repo_fetcher import RepoFetcher
from graph_kb_api.graph_kb.services._legacy_indexer_service import IndexerService
from graph_kb_api.graph_kb.storage import MetadataStore
from graph_kb_api.graph_kb.storage.graph_store import Neo4jGraphStore
from graph_kb_api.graph_kb.storage.vector_store import ChromaVectorStore


@dataclass
class ParsedThreadId:
    """
    Parsed components of a thread ID.

    Thread IDs follow the format: {user_id}_{session_id}_{repo_id}
    where repo_id is optional.

    Attributes:
        user_id: User identifier
        session_id: Session identifier
        repo_id: Optional repository identifier
    """

    user_id: str
    session_id: str
    repo_id: Optional[str] = None


class ServiceRegistry(TypedDict, total=False):
    """
    Service registry dictionary passed to workflow nodes.

    This dictionary contains all services that nodes may need to access
    during workflow execution. Services are injected through the workflow
    configuration and made available to nodes via the services parameter.

    All fields use proper type hints with TYPE_CHECKING to avoid circular
    imports while maintaining full type safety and IDE support.

    Attributes:
        app_context: Application context with RAG, LLM, and other core services
        messenger: Workflow messenger for sending messages to users
        file_discovery: File system discovery service for repository analysis
        repo_fetcher: Repository fetcher for git operations (clone, update)
        indexer_service: Indexing service for repository ingestion
        metadata_store: Metadata store for repository and file tracking
        graph_store: Neo4j graph store for code structure
        vector_store: ChromaDB vector store for embeddings
        embedding_generator: Embedding generator for vector creation
    """

    # Core application services (used by most workflows)
    app_context: NotRequired[AppContext]
    file_discovery: NotRequired[FileSystemDiscovery]

    # Graph KB services (used by ingest workflow)
    repo_fetcher: NotRequired[RepoFetcher]
    indexer_service: NotRequired[IndexerService]
    metadata_store: NotRequired[MetadataStore]
    graph_store: NotRequired[Neo4jGraphStore]
    vector_store: NotRequired[ChromaVectorStore]
    embedding_generator: NotRequired[EmbeddingGenerator]


class ThreadConfigurable(TypedDict, total=False):
    """
    Structure of the 'configurable' dict within RunnableConfig for our workflows.

    LangGraph's RunnableConfig has a `configurable: dict[str, Any]` field that
    can contain arbitrary configuration. We use it to pass:
    - thread_id (required by LangGraph for checkpointing)
    - user_id, session_id, repo_id (our workflow metadata)
    - services (dependency injection for workflow nodes)
    - WorkflowContext fields (auto-injected by get_config_with_services)

    This TypedDict documents our specific usage of the configurable dict,
    but the actual type is just `dict[str, Any]` in RunnableConfig.

    Attributes:
        thread_id: Unique thread identifier (format: {user_id}_{session_id}_{repo_id})
                   Required by LangGraph for state persistence
        user_id: User identifier (our custom field)
        session_id: Session identifier (our custom field)
        repo_id: Optional repository identifier (our custom field)
        services: Service registry for dependency injection (our custom field)
    """

    # LangGraph required
    thread_id: str

    # Workflow metadata
    user_id: str
    session_id: str
    repo_id: NotRequired[str]
    client_id: NotRequired[str]

    # Dependency injection
    services: NotRequired[ServiceRegistry]
    context: NotRequired[WorkflowContext]  # backward-compat alias for WorkflowContext
    llm: NotRequired[LLMService]
    artifact_service: NotRequired[ArtifactService]
    progress_callback: NotRequired[Callable[[ProgressEvent], Awaitable[None]]]

    # Auto-injected by get_config_with_services() from WorkflowContext fields
    app_context: NotRequired[AppContext]
    blob_storage: NotRequired[BlobStorage]
    checkpointer: NotRequired[BaseCheckpointSaver]
    graph_store: NotRequired[GraphKBFacade]
    vector_store: NotRequired[ChromaVectorStore]
    fingerprint_tracker: NotRequired[FingerprintTracker]


class ThreadConfig(TypedDict):
    """
    Documentation type showing our usage of RunnableConfig's configurable field.

    This TypedDict documents the structure we create, but the actual return type
    of create_thread_config is RunnableConfig (from LangGraph). RunnableConfig
    has many optional fields, but we primarily use:
    - configurable: dict[str, Any] - where we put our thread/user/service info

    The configurable dict can contain any keys (it's dict[str, Any]), so we're
    free to add our custom fields like user_id, session_id, services, etc.
    LangGraph only requires thread_id for checkpointing.

    Note: Use RunnableConfig as the actual type in function signatures.
    This type is for documentation only.

    Attributes:
        configurable: Thread configuration and metadata (see ThreadConfigurable)
    """

    configurable: ThreadConfigurable


class PathNodeDict(TypedDict):
    """
    Type definition for a node in a call chain path.

    Used by GraphKB tools to represent individual nodes in traced call chains.
    Each node contains information about a code symbol and its location.

    Attributes:
        name: Symbol name (function, class, method)
        file_path: Path to the file containing the symbol (may be None)
        line_number: Line number where the symbol is defined (may be None)
        node_id: Unique node identifier in the graph database
    """

    name: str
    file_path: Optional[str]
    line_number: Optional[int]
    node_id: str


@dataclass
class AgentCapability:
    """
    Describes what an agent can do.

    This dataclass provides metadata about an agent's capabilities
    including which tasks it can handle, which tools it requires,
    and its system prompt.
    """

    agent_type: str
    supported_tasks: List[str]
    required_tools: List[str]
    optional_tools: List[str]
    description: str
    system_prompt: str


class AgentTask(TypedDict, total=False):
    """
    Task definition passed to agent.execute().

    Attributes:
        description: Human-readable task description
        title: Optional section/task title for the LLM prompt
        task_id: Unique identifier for the task
        context: Additional context data relevant to the task
        priority: Optional priority level (e.g., "high", "medium", "low")
        tools: Optional list of tools the agent should use
        specification: Specification metadata (name, explanation) for the task
        research_findings: Research findings data for gap analysis tasks
    """

    description: str
    title: str
    task_id: str
    context: Dict[str, Any]
    priority: str
    tools: List[str]
    specification: Dict[str, Any]
    research_findings: Dict[str, Any]


class AgentResult(TypedDict, total=False):
    """
    Result returned from agent.execute().

    Attributes:
        output: Primary output/result from the agent
        agent_draft: Draft content (for spec-generating agents)
        agent_type: Type identifier of the agent that produced this result
        confidence_score: Confidence level 0.0-1.0
        confidence_rationale: Explanation of confidence level
        tokens: Token usage for this execution
        error: Error message if execution failed
        gaps: List of detected gaps (gap analysis agent)
        completeness_score: Completeness score 0.0-1.0 (gap analysis agent)
        summary: Summary text (gap analysis agent)
        task_tool_assignments: Tool assignments per task (tool planner agent)
        workflow_initiated: Whether a workflow was started (feature spec agent)
        task: Task payload forwarded to the workflow handler (feature spec agent)
    """

    output: Any
    agent_draft: str
    agent_type: str
    confidence_score: float
    confidence_rationale: str
    tokens: int
    error: str
    gaps: List[Dict[str, Any]]
    completeness_score: float
    summary: str
    task_tool_assignments: Dict[str, List[str]]
    workflow_initiated: bool
    task: Dict[str, Any]


class CritiqueResult(TypedDict):
    """Result from an agent critique review.

    Attributes:
        approved: Whether the critiqued output meets quality standards.
        score: Confidence score 0.0-1.0.
        feedback: Human-readable explanation of the critique decision.
    """

    approved: bool
    score: float
    feedback: str


# ---------------------------------------------------------------------------
# Shared data models used by multi-agent workflow agents
# ---------------------------------------------------------------------------


@dataclass
class GapInfo:
    """Information about a detected gap requiring human input.

    Created when the system identifies missing information that cannot be
    resolved by agents alone — either proactively during context retrieval
    or by the reviewer during draft evaluation.
    """

    gap_id: str
    section_id: str
    gap_type: str
    description: str
    question: str
    context: str
    source: str
    resolved: bool = False
    resolution: Optional[str] = None

    def validate(self) -> List[str]:
        """Return a list of validation error messages (empty if valid)."""
        errors: List[str] = []
        if not self.gap_id:
            errors.append("gap_id is required")
        if not self.question:
            errors.append("question is required")
        return errors


@dataclass
class ReviewResult:
    """Result from the reviewer/critic agent.

    Contains the verdict, quality score, feedback, and any gaps detected
    during review. The scrutiny_level reflects how deeply the review was
    conducted based on the producing agent's confidence score.
    """

    verdict: str
    score: float
    feedback: str
    missing_items: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    gaps: List[GapInfo] = field(default_factory=list)
    scrutiny_level: str = "standard"


@dataclass
class ConsistencyIssue:
    """A cross-section consistency issue detected by ConsistencyCheckerAgent.

    Represents a mismatch, naming inconsistency, diagram misalignment, or
    contradiction found between completed sections.
    """

    issue_id: str
    issue_type: str
    description: str
    affected_sections: List[str] = field(default_factory=list)
    severity: str = "warning"
    suggested_fix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict."""
        from dataclasses import asdict
        return asdict(self)

    def validate(self) -> List[str]:
        """Return a list of validation error messages (empty if valid)."""
        errors: List[str] = []
        if not self.issue_id:
            errors.append("issue_id is required")
        if not self.description:
            errors.append("description is required")
        return errors


# ---------------------------------------------------------------------------
# Agent capability factory functions
# ---------------------------------------------------------------------------
# These create AgentCapability instances for each agent type. Used by
# the concrete agent classes and for validation/testing.
# ---------------------------------------------------------------------------


def architect_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Architect agent."""
    return AgentCapability(
        agent_type="architect",
        supported_tasks=[
            "architecture_overview",
            "component_design",
            "data_flow",
            "system_boundaries",
            "integration_points",
        ],
        required_tools=[
            "search_code",
            "get_symbol_info",
            "trace_call_chain",
        ],
        optional_tools=["get_file_content", "execute_cypher_query"],
        description="Designs architecture and high-level system structure",
        system_prompt=system_prompt,
    )


def lead_engineer_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Lead Engineer agent."""
    return AgentCapability(
        agent_type="lead_engineer",
        supported_tasks=[
            "api_design",
            "data_models",
            "error_handling",
            "testing_strategy",
            "performance_requirements",
            "security_considerations",
        ],
        required_tools=[
            "search_code",
            "get_symbol_info",
            "get_file_content",
        ],
        optional_tools=["trace_call_chain", "get_related_files"],
        description="Designs implementation details and API contracts",
        system_prompt=system_prompt,
    )


def doc_extractor_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Doc Extractor agent."""
    return AgentCapability(
        agent_type="doc_extractor",
        supported_tasks=[
            "openapi_extraction",
            "document_synthesis",
            "requirement_extraction",
            "constraint_identification",
        ],
        required_tools=["get_file_content", "search_code"],
        optional_tools=["get_related_files"],
        description="Extracts and synthesizes info from supplementary documents",
        system_prompt=system_prompt,
    )


def reviewer_critic_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Reviewer/Critic agent."""
    return AgentCapability(
        agent_type="reviewer_critic",
        supported_tasks=[
            "completeness_review",
            "accuracy_review",
            "consistency_review",
            "template_alignment",
        ],
        required_tools=["search_code", "get_symbol_info"],
        optional_tools=["get_file_content"],
        description="Reviews agent outputs with confidence-aware prioritization",
        system_prompt=system_prompt,
    )


def tool_planner_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Tool Planner agent."""
    return AgentCapability(
        agent_type="tool_planner",
        supported_tasks=[
            "tool_planning",
            "context_estimation",
            "tool_replanning",
        ],
        required_tools=[],
        optional_tools=[],
        description="Plans which tools each agent needs per task (re-invocable)",
        system_prompt=system_prompt,
    )


def consistency_checker_capability(system_prompt: str = "") -> AgentCapability:
    """Create AgentCapability for the Consistency Checker agent."""
    return AgentCapability(
        agent_type="consistency_checker",
        supported_tasks=[
            "cross_reference_validation",
            "naming_consistency",
            "diagram_alignment",
            "data_model_consistency",
        ],
        required_tools=["search_code"],
        optional_tools=["get_symbol_info"],
        description="Verifies cross-section consistency periodically",
        system_prompt=system_prompt,
    )
