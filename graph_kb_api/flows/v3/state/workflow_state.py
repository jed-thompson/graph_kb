"""
Workflow State schema for multi-phase DAG workflows.

Defines phase-specific TypedDicts and workflow constants shared across
workflow engines (plan, spec, etc.).

Each phase owns a TypedDict with operator.or_ reducers for merge-on-update semantics.

Workflow Constraints (MUST ENFORCE):
- Max Context Gathering Rounds: 5
- Max LLM Review Loops: 5
- Max Critique Iterations per Task: 3
- Max Completeness Review Loop-back: 1
- Research Subtask Timeout: 60s
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Literal, Optional

from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict

# ── Constants ─────────────────────────────────────────────────────

PHASE_ORDER: List[str] = ["context", "review", "research", "plan", "orchestrate", "completeness", "generate"]

MAX_CONTEXT_ROUNDS: int = 5
MAX_REVIEW_LOOPS: int = 5
MAX_CRITIQUE_ITERATIONS: int = 3
MAX_COMPLETENESS_LOOPS: int = 1
MAX_CONSISTENCY_ITERATIONS: int = 3
MAX_RESEARCH_GAP_ITERATIONS: int = 3  # Loop guard for research gap-check loop
RESEARCH_SUBTASK_TIMEOUT: int = 60  # seconds


# ── Phase-specific data TypedDicts ───────────────────────────────


class ContextRound(TypedDict, total=False):
    """Single interaction round in context gathering (C1-C8)."""

    round_number: int
    prompt_type: Literal["guidance", "additional_context", "clarification"]
    user_input: str
    uploaded_docs: List[str]
    selected_template: Optional[str]
    timestamp: str


class ContextData(TypedDict, total=False):
    """Data collected during the iterative context phase (C1-C8)."""

    # Basic info
    spec_name: str
    spec_description: str

    # Iterative context gathering
    rounds: List[ContextRound]
    round_count: int
    guidance_type: Literal["text", "doc", "template"]
    is_complete: bool  # User signaled completion

    # Document references
    primary_document_id: str
    primary_document_type: str
    supporting_doc_ids: List[str]

    # User input
    user_explanation: str
    constraints: str  # Free-text constraints from user form

    # Validation (ValidateContextNode)
    validated: bool
    is_empty: bool
    validation_errors: List[Dict[str, Any]]  # each: {field, message, severity}

    # Deep analysis (DeepAnalysisNode)
    deep_analysis_ref: Dict[str, Any]  # ArtifactRef shape when artifact_svc available
    deep_analysis_full: Dict[str, Any]  # Full analysis report

    # Feedback round (FeedbackReviewNode)
    user_clarifications: Dict[str, Any]
    additional_context_from_review: str
    architecture_feedback: Dict[str, Any]

    # Template selection (G1-G2)
    template_id: Optional[str]

    # Target repository
    target_repo_id: str

    # URLs extracted for research
    extracted_urls: List[str]
    reference_urls: List[str]

    # Fetched reference documents (inline content for research phase)
    reference_documents: List[Dict[str, str]]

    # Uploaded document contents (inline content for LLM prompts)
    uploaded_document_contents: List[Dict[str, str]]  # [{doc_id, filename, content, role}]

    # Composite section index covering ALL uploaded documents (primary + supporting + reference URLs)
    # Built by CollectContextNode from uploaded_document_contents.
    # Each entry: {doc_id, filename, role, sections: [{heading, level, start_char, end_char, token_count}]}
    document_section_index: List[Dict[str, Any]]

    # Artifact-backed URL metadata (for frontend retrieval)
    reference_urls_meta: List[Dict[str, Any]]


class ReviewData(TypedDict, total=False):
    """Data produced during the LLM review phase (R1-R8)."""

    # LLM analysis results
    analysis: Dict[str, Any]
    gaps: Dict[str, Any]  # keyed by gap identifier, not a flat list
    clarification_questions: List[Dict[str, Any]]  # each has {id, question, context, suggested_answers}

    # Review scoring
    completeness_score: float  # 0.0-1.0, set by ReviewNode
    summary: str
    suggested_actions: List[str]

    # User interaction
    user_decision: Literal["add_context", "clarify", "proceed"]
    user_response: Optional[str]

    # State tracking
    approved: bool
    review_loop_count: int

    # Feedback round
    answered_questions: List[Dict[str, Any]]  # each has {question_id, answer}


class ResearchSubtask(TypedDict, total=False):
    """Single research subtask (RE2-RE5)."""

    subtask_id: str
    task_type: Literal["web", "vector", "graph"]
    query: str
    urls: Optional[List[str]]
    repos: Optional[List[str]]
    status: Literal["pending", "running", "complete", "failed"]
    result: Optional[Dict[str, Any]]
    error: Optional[str]


class ResearchData(TypedDict, total=False):
    """Data produced during the research phase (RE1-RE5)."""

    # Target extraction
    targets: Dict[str, Any]

    # Subtask decomposition
    subtasks: List[ResearchSubtask]
    queries: List[Dict[str, Any]]  # Formulated research queries from FormulateQueriesNode

    # Aggregated results
    web_results: List[Dict[str, Any]]
    vector_results: List[Dict[str, Any]]
    graph_results: List[Dict[str, Any]]

    # Combined findings
    findings: Dict[str, Any]
    gaps: List[Dict[str, Any]]
    gap_responses: Dict[str, str]

    # Confidence scoring
    confidence_score: float  # 0.0-1.0, set by ConfidenceGateNode
    confidence_sufficient: bool  # True if score >= 0.7
    confidence_evaluation_method: str  # always "llm"
    confidence_gap: float  # 0.7 - score when insufficient
    can_proceed_to_approval: bool
    needs_more_research: bool  # True when confidence insufficient and iterations remain

    # Loop guard
    research_gap_iterations: int  # Incremented by GapCheckNode

    # Data availability signal from dispatch_research
    structured_data_available: bool

    # Persistence
    findings_doc_id: str  # Document ID for persisted aggregated findings

    # Approval
    approved: bool
    approval_decision: str  # "approve", "request_more", or "reject"
    approval_feedback: str
    review_feedback: str
    rejected: bool  # True when user rejects research


class AgentAssignment(TypedDict, total=False):
    """Agent + tool assignment for a task (P3-P4)."""

    task_id: str
    agent_type: str  # e.g., "research", "architect", "frontend", "backend"
    tools: List[str]  # e.g., ["neo4j", "vector_store", "websearch"]
    context_requirements: List[str]
    complexity: Literal["low", "medium", "high"]


class PlanData(TypedDict, total=False):
    """Data produced during the plan phase (P1-P5)."""

    # Roadmap
    roadmap: Dict[str, Any]
    feasibility: Dict[str, Any]

    # Agent/tool assignments
    agent_assignments: List[AgentAssignment]
    tool_configuration: Dict[str, Any]

    # Tasks decomposed from research
    tasks: List[Dict[str, Any]]

    # Task DAG (DecomposeNode)
    task_dag: Dict[str, Any]  # {tasks, dag_edges, entry_tasks, exit_tasks, ...}

    # DAG validation (ValidateDagNode)
    dag_validation: Dict[str, Any]  # {is_valid, errors, warnings}
    dag_valid: bool  # Legacy; prefer dag_validation.is_valid
    dag_errors: List[str]  # Legacy; prefer dag_validation.errors

    # Agent assignments per task (AssignNode)
    assignments: List[Dict[str, Any]]  # [{task_id, agent_type, tools, skills_required, reasoning}]

    # Coverage and alignment
    coverage_matrix: Dict[str, Any]  # requirements -> tasks mapping
    alignment: Dict[str, Any]  # {is_aligned, constraints_met, constraints_violated, ...}
    alignment_score: float  # 0.0-1.0, set by AlignNode

    # Approval
    approved: bool
    approval_decision: str  # "approve", "revise", or "reject"
    approval_feedback: str
    review_feedback: str
    needs_revision: bool  # True when user requests revision
    rejected: bool  # True when user rejects plan


class TaskIteration(TypedDict, total=False):
    """Single iteration in the critique loop (O3-O6)."""

    iteration: int
    task_id: str
    result: Dict[str, Any]
    critique: Dict[str, Any]
    approved: bool
    feedback: str


class OrchestrateData(TypedDict, total=False):
    """Data produced during the orchestration phase (O1-O9)."""

    # Current task dispatch
    current_task: Dict[str, Any]  # The currently executing task
    current_task_index: int
    current_task_context: Dict[str, Any]  # Hydrated context for current task
    total_tasks: int

    # Task selection (TaskSelectorNode)
    ready_tasks: List[str]  # Task IDs ready to execute
    blocked: bool  # True when all remaining tasks have unmet dependencies

    # Context gaps for current task
    context_gaps: List[Dict[str, Any]]  # Detected gaps in task context

    # Tool planning
    tool_assignments: Dict[str, Any]  # Tools assigned for current task

    # Agent dispatch
    assigned_agent: str  # Agent type for current task (architect, research, etc.)
    agent_context: Dict[str, Any]  # Context built for agent execution

    # Current task output
    current_draft: str  # Summary of current task draft

    # Per-task iterations (critique loop)
    task_iterations: Dict[str, List[TaskIteration]]  # task_id -> iterations

    # Critique results (ROUTING FIELD)
    critique_passed: bool  # Set by CritiqueNode - drives _route_after_critique
    critique_feedback: str
    critique_history: List[Dict[str, Any]]  # [{task_id, iteration, verdict, score}]

    # Aggregated results
    task_results: List[Dict[str, Any]]

    # Critique loop counter
    iteration_count: int  # Incremented by CritiqueNode per task

    # Overall status
    all_complete: bool


class CompletenessData(TypedDict, total=False):
    """Data produced during the completeness review phase (CO1-CO5)."""

    # Completeness check (CompletenessNode)
    completeness_check: Dict[str, Any]  # {is_complete, completeness_score, completed_tasks, ...}

    # Review result
    review_result: Dict[str, Any]

    # Gap analysis
    gaps_found: bool
    gaps: List[Dict[str, Any]]

    # Loop-back control
    gap_tasks: List[Dict[str, Any]]
    review_loop_count: int  # Max 1

    # Validation (ValidateNode)
    validation: Dict[str, Any]  # {is_valid, errors, warnings}

    # Consistency check (moved from GenerateData per GAP 0d)
    consistency_issues: List[Dict[str, Any]]  # Set by ConsistencyNode - drives _route_after_consistency
    consistency_iterations: int  # Incremented by ConsistencyNode

    # Status
    complete: bool

    # Approval (AssemblyApprovalNode)
    approved: bool
    approval_decision: str  # "approve", "revise", or "reject"
    approval_feedback: str
    needs_revision: bool
    rejected: bool


class DecomposeData(TypedDict, total=False):
    """Data produced during the decompose phase (legacy, kept for compatibility)."""

    stories: List[Dict[str, Any]]
    tasks: List[Dict[str, Any]]
    dependency_graph: Dict[str, List[str]]
    approved: bool
    review_feedback: str


class GenerateData(TypedDict, total=False):
    """Data produced during the generate phase (G1-G9)."""

    # Template selection
    template_id: str
    template_loaded: bool
    template: Dict[str, Any]  # {content, variables, spec_name, phases_count}

    # Generated content
    sections: Dict[str, str]

    # Output
    spec_document_path: str
    story_cards_path: str
    flow_score: float  # 0.0-1.0, set by AssembleNode

    # Generation loop control
    generation_iteration: int


# ── Navigation state ─────────────────────────────────────────────


class NavigationState(TypedDict, total=False):
    """Tracks current position and direction within the multi-phase flow."""

    current_phase: str
    direction: Literal["forward", "backward"]
    target_phase: Optional[str]  # For backward navigation
    cascade_warning: Dict[str, Any]


# ── Progress tracking ─────────────────────────────────────────────


class ProgressStep(TypedDict, total=False):
    """Single step in phase progress tracking."""

    step: str  # e.g., "research.web_search"
    phase: str
    message: str
    status: Literal["pending", "active", "complete", "failed"]
    timestamp: Optional[str]


class ProgressData(TypedDict, total=False):
    """Progress tracking for UI blocking."""

    progress_steps: List[ProgressStep]
    progress_percent: int  # 0-100, or -1 for indeterminate
    is_blocked: bool
    can_cancel: bool


# ── Unified top-level state ──────────────────────────────────────


class UnifiedSpecState(TypedDict):
    """Consolidated state for spec generation with 7-phase DAG.

    Phase order: context → review → research → plan → orchestrate → completeness → generate

    State Transitions:
        START → context → review → research → plan → orchestrate → completeness → generate → END
                    ↑______________|                           ↓
                             (single loop-back allowed from review)
                                                          ↓
                                        (single loop-back allowed from completeness)

    Uses operator.or_ reducers on phase data dicts so that partial
    updates merge with existing values instead of replacing them.
    """

    # Navigation
    navigation: NavigationState

    # Phase data (nested, clear ownership)
    context: Annotated[ContextData, operator.or_]
    review: Annotated[ReviewData, operator.or_]
    research: Annotated[ResearchData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    orchestrate: Annotated[OrchestrateData, operator.or_]
    completeness: Annotated[CompletenessData, operator.or_]
    generate: Annotated[GenerateData, operator.or_]

    # Legacy phase (kept for backward compatibility)
    decompose: Annotated[DecomposeData, operator.or_]

    # Progress tracking
    progress: NotRequired[ProgressData]

    # Workflow control
    mode: Literal["wizard", "quick"]
    workflow_status: Literal["idle", "running", "paused", "completed", "error"]
    error: NotRequired[Dict[str, Any]]

    # Phase completion tracking
    completed_phases: Annotated[Dict[str, bool], operator.or_]

    # Loop counters (for constraint enforcement)
    context_round_count: NotRequired[int]
    review_loop_count: NotRequired[int]
    completeness_loop_count: NotRequired[int]

    # Session persistence
    session_id: NotRequired[str]

    # Messages for LangGraph
    messages: Annotated[list, add_messages]
