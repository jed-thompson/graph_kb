from __future__ import annotations

"""PlanState schema for the /plan command built on LangGraph."""

import operator
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Union

from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict

from graph_kb_api.flows.v3.state.workflow_state import (
    CompletenessData,
    ContextData,
    GenerateData,
    NavigationState,
    OrchestrateData,
    PlanData,
    ResearchData,
    ReviewData,
)


class PlanPhase(str, Enum):
    """Canonical identifiers for each plan workflow phase."""

    CONTEXT = "context"
    RESEARCH = "research"
    PLANNING = "planning"
    ORCHESTRATE = "orchestrate"
    ASSEMBLY = "assembly"


def _last_write_wins(existing: dict, update: dict) -> dict:
    """Reducer for completed_phases: incoming values always overwrite existing.

    Unlike ``operator.or_`` which merges dicts (and could lose ``False`` values
    when combining with existing ``True`` entries in edge cases), this
    explicitly gives precedence to the update dict for any overlapping keys.
    """
    return {**existing, **update}


def _capped_list_add(max_entries: int = 50):
    """Reducer that appends lists but caps the result to *max_entries*.

    Prevents unbounded checkpoint growth during long orchestrate phases
    (e.g. 10 tasks x 3 iterations = 100+ entries).
    """

    def reducer(existing: list, update: list) -> list:
        combined = existing + update
        return combined[-max_entries:]

    return reducer


# Severity ordering for workflow_status: higher = more final.
# Once a workflow enters a severe state (error, budget_exhausted, rejected,
# paused), a subsequent node MUST NOT revert it to "running" or "idle"
# — except when navigate_to_phase explicitly resets to "running" for
# backward navigation after rejection/error.
_STATUS_SEVERITY: dict[str, int] = {
    "idle": 0,
    "running": 1,
    "paused": 2,
    "error": 3,
    "budget_exhausted": 3,
    "rejected": 3,
    "completed": 4,
}


def _workflow_status_reducer(existing: str, update: str) -> str:
    """Reducer that prevents status regression during normal execution.

    Nodes returning ``workflow_status="running"`` cannot overwrite an
    existing ``"error"`` or ``"paused"`` — only equal-or-higher severity
    values are accepted.

    Exception: ``navigate_to_phase`` explicitly resets to ``"running"``
    so that backward navigation after rejection/error works correctly.
    This is the ONLY place ``"running"`` should override a halt status.
    """
    existing_sev = _STATUS_SEVERITY.get(existing, 0)
    update_sev = _STATUS_SEVERITY.get(update, 0)
    if update == "running" and existing_sev >= 2:
        # Allow explicit navigation reset (navigate_to_phase sets "running").
        # Nodes must NEVER set this during normal execution.
        return update
    return update if update_sev >= existing_sev else existing


class ArtifactRef(TypedDict):
    """Lightweight reference to content in blob storage."""

    key: str
    content_hash: str
    size_bytes: int
    created_at: str
    summary: str


class DocumentManifestEntry(TypedDict):
    """Tracks a single deliverable document produced by orchestration."""

    task_id: str
    task_name: str  # human-readable section title (e.g. "OntTrac Purchase Label Contract Freeze")
    spec_section: str  # e.g. "5.3 Rates & Transit Times"
    artifact_ref: ArtifactRef
    status: str  # "draft" | "reviewed" | "final" | "failed" | "error"
    section_type: str  # from task DAG (analysis_and_draft, etc.)
    dependencies: list[str]  # task_ids this doc references
    token_count: int
    error_message: str | None  # set when status is "failed" or "error"
    composed_at: str | None  # ISO timestamp when promoted to final


class DocumentManifest(TypedDict):
    """The complete output document suite for a plan session."""

    session_id: str
    spec_name: str
    primary_spec_ref: ArtifactRef | None  # nullable for sessions without uploaded docs
    entries: list[DocumentManifestEntry]
    composed_index_ref: ArtifactRef | None
    total_documents: int
    total_tokens: int
    created_at: str
    finalized_at: str | None


def create_empty_manifest(session_id: str, spec_name: str) -> DocumentManifest:
    """Factory for an empty DocumentManifest with default field values.

    Replaces inline initialization blocks in BudgetCheckNode, TaskSelectorNode,
    and WorkerNode.

    Args:
        session_id: Current plan session identifier.
        spec_name: Name of the specification being processed.

    Returns:
        A DocumentManifest dict with empty entries and zeroed counters.
    """
    return DocumentManifest(
        session_id=session_id,
        spec_name=spec_name,
        primary_spec_ref=None,
        entries=[],
        composed_index_ref=None,
        total_documents=0,
        total_tokens=0,
        created_at=datetime.now(UTC).isoformat(),
        finalized_at=None,
    )


class BudgetState(TypedDict, total=False):
    """Global budget counters decremented by each LLM-calling node."""

    max_llm_calls: int
    remaining_llm_calls: int
    max_tokens: int
    tokens_used: int
    max_wall_clock_s: int
    started_at: str


def _budget_reducer(existing: BudgetState, update: BudgetState) -> BudgetState:
    """Merge-style reducer for BudgetState that prevents stale overwrites.

    Rules:
    * ``remaining_llm_calls``: take the **minimum** of both sides so that
      decrements from any node are never silently overwritten by a stale
      snapshot.
    * ``tokens_used``: take the **maximum** so token consumption is
      monotonically increasing.
    * ``max_llm_calls``, ``max_tokens``, ``max_wall_clock_s``: take the
      update value when present (these are set intentionally by budget
      increase logic, not drift-prone).
    * ``started_at``: take the update value when present (reset by
      budget increase).
    """
    merged: BudgetState = {**existing, **update}

    if "remaining_llm_calls" in existing and "remaining_llm_calls" in update:
        merged["remaining_llm_calls"] = min(
            existing["remaining_llm_calls"], update["remaining_llm_calls"]
        )
    if "tokens_used" in existing and "tokens_used" in update:
        merged["tokens_used"] = max(existing["tokens_used"], update["tokens_used"])

    return merged


# ── Interrupt Payload Types ─────────────────────────────────────


class InterruptOption(TypedDict):
    id: str
    label: str


class ArtifactManifestEntry(TypedDict):
    key: str
    summary: str
    size_bytes: int
    created_at: str
    content_type: str


class WorkflowError(TypedDict):
    """Structured error dict stored in state and emitted via WebSocket."""

    message: str
    code: str
    phase: str


class ProgressEvent(TypedDict):
    """Payload shape for progress callback emissions."""

    session_id: str
    phase: str
    step: str
    message: str
    percent: float


class ContextItemsSummary(TypedDict, total=False):
    """Lightweight context summary for interrupt payloads and DB snapshots.

    Produced by ``build_context_items_summary()`` and ``_load_context_items()``.
    Contains the non-bulky subset of ContextData fields plus DB-persisted items
    from FeedbackReviewNode.
    """

    # From ContextData (non-bulky fields)
    spec_name: str
    spec_description: str
    user_explanation: str
    constraints: str
    primary_document_id: str
    supporting_doc_ids: List[str]
    target_repo_id: str
    validated: bool

    # From FeedbackReviewNode DB persistence
    extracted_urls: List[Dict[str, Any]]  # [{url, document_id?, summary?, size_bytes?}]
    rounds: List[Dict[str, Any]]  # ContextRound dicts
    reference_urls_meta: List[Dict[str, Any]]


class ApprovalInterruptPayload(TypedDict):
    """Payload for approval-type interrupts (research/planning/assembly/budget).

    Required fields are always present at every call site.
    Optional fields vary: context_items is omitted by budget interrupt,
    tasks is only on PlanningApprovalNode.
    """

    type: Literal["approval"]
    phase: str
    step: str
    summary: Dict[str, Any]
    message: str
    options: List[InterruptOption]
    artifacts: List[ArtifactManifestEntry]
    context_items: NotRequired[ContextItemsSummary]
    tasks: NotRequired[List[Dict[str, Any]]]
    task_results: NotRequired[List[Dict[str, Any]]]


class AnalysisReviewInterruptPayload(TypedDict):
    """Payload for analysis review interrupts (FeedbackReviewNode)."""

    type: Literal["analysis_review"]
    phase: str
    step: str
    completeness_score: float
    gaps: list[dict[str, Any]]
    clarification_questions: list[dict[str, Any]]
    suggested_actions: list[dict[str, Any]]
    architecture_analysis: Dict[str, Any]
    message: str
    context_items: ContextItemsSummary
    artifacts: List[ArtifactManifestEntry]


class FormInterruptPayload(TypedDict):
    """Payload for form-style interrupts (CollectContextNode)."""

    type: Literal["form"]
    phase: str
    step: str
    fields: List[Dict[str, Any]]
    prefilled: NotRequired[Dict[str, Any]]


class TaskContextInterruptPayload(TypedDict):
    """Payload for per-task context input interrupts (TaskContextInputNode)."""

    type: Literal["task_context_input"]
    task_name: str
    spec_section: str
    context_gaps: List[str]
    task_results: NotRequired[List[Dict[str, Any]]]


PlanInterruptPayload = Union[
    ApprovalInterruptPayload,
    AnalysisReviewInterruptPayload,
    FormInterruptPayload,
    TaskContextInterruptPayload,
]


class TransitionEntry(TypedDict):
    """Single graph transition for audit trail."""

    timestamp: str
    from_node: str
    to_node: str
    subgraph: str
    reason: str
    budget_snapshot: Dict[str, int]


class PhaseFingerprint(TypedDict):
    """Tracks what input produced a phase output."""

    phase: str
    input_hash: str
    output_refs: List[str]
    completed_at: str


def _manifest_reducer(
    existing: DocumentManifest | None,
    update: DocumentManifest | None,
) -> DocumentManifest | None:
    """Custom reducer for document_manifest: shallow-merge scalar fields, upsert entries by task_id."""
    if update is None:
        return existing
    if existing is None:
        return update

    existing_map = {e["task_id"]: e for e in existing.get("entries", [])}
    for entry in update.get("entries", []):
        existing_map[entry["task_id"]] = entry  # upsert

    return {
        **existing,
        **{k: v for k, v in update.items() if k != "entries"},
        "entries": list(existing_map.values()),
    }


class BasePlanSubgraphState(TypedDict):
    """Shared fields for all plan subgraph states.

    All plan subgraph state classes inherit from this base, declaring only
    phase-specific fields.  LangGraph's ``StateGraph`` resolves annotations
    via ``get_type_hints(include_extras=True)`` which traverses the MRO,
    so reducer annotations on these shared fields are preserved in every
    subclass.
    """

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    session_id: NotRequired[str]
    workflow_status: Annotated[
        Literal[
            "idle", "running", "paused", "completed", "error",
            "budget_exhausted", "rejected",
        ],
        _workflow_status_reducer,
    ]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class PlanState(BasePlanSubgraphState):
    """Consolidated state for the /plan command with hybrid storage."""

    context: Annotated[ContextData, operator.or_]
    review: Annotated[ReviewData, operator.or_]
    research: Annotated[ResearchData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    orchestrate: Annotated[OrchestrateData, operator.or_]
    completeness: Annotated[CompletenessData, operator.or_]
    generate: Annotated[GenerateData, operator.or_]
    # Multi-document manifest (top-level so it survives prune nodes
    # and is accessible across orchestrate + assembly subgraphs).
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    # Re-orchestration flags (set by CompositionReviewNode, consumed by PlanEngine).
    needs_re_orchestrate: NotRequired[bool]
    re_execute_task_ids: NotRequired[list[str]]
    re_orchestration_count: NotRequired[int]
    error: NotRequired[WorkflowError]


class ContextSubgraphState(BasePlanSubgraphState):
    """State for the context subgraph."""

    context: Annotated[ContextData, operator.or_]
    review: Annotated[ReviewData, operator.or_]


class ResearchSubgraphState(BasePlanSubgraphState):
    """State for the research subgraph."""

    context: Annotated[ContextData, operator.or_]  # For FormulateQueriesNode, GapCheckNode
    review: Annotated[ReviewData, operator.or_]  # For ReviewNode, DeepAnalysisNode
    research: Annotated[ResearchData, operator.or_]


class PlanningSubgraphState(BasePlanSubgraphState):
    """State for the planning subgraph."""

    context: Annotated[ContextData, operator.or_]  # For RoadmapNode, FeasibilityNode, DecomposeNode, AlignNode, AssignNode
    research: Annotated[ResearchData, operator.or_]  # For all planning nodes
    plan: Annotated[PlanData, operator.or_]


class OrchestrateSubgraphState(BasePlanSubgraphState):
    """State for the orchestrate subgraph."""

    context: Annotated[ContextData, operator.or_]  # For FetchContextNode, TaskResearchNode
    research: Annotated[ResearchData, operator.or_]  # For TaskResearchNode, FetchContextNode
    orchestrate: Annotated[OrchestrateData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    # Multi-document manifest — must be present in subgraph state for
    # WorkerNode read-modify-write (LangGraph subgraph states are independent
    # schemas; keys not declared here are silently dropped from node outputs).
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    error: NotRequired[WorkflowError]


class AssemblySubgraphState(BasePlanSubgraphState):
    """State for the assembly subgraph."""

    orchestrate: Annotated[OrchestrateData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    context: Annotated[ContextData, operator.or_]
    research: Annotated[ResearchData, operator.or_]
    completeness: Annotated[CompletenessData, operator.or_]
    generate: Annotated[GenerateData, operator.or_]
    # Multi-document manifest — must be present so GenerateNode, CompositionReviewNode,
    # AssembleNode, and FinalizeNode can read/write manifest entries within this subgraph.
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    # Re-orchestration flags (set by CompositionReviewNode, consumed by PlanEngine).
    needs_re_orchestrate: NotRequired[bool]
    re_execute_task_ids: NotRequired[list[str]]
    re_orchestration_count: NotRequired[int]


CASCADE_MAP: Dict[PlanPhase, List[PlanPhase]] = {
    PlanPhase.CONTEXT: [PlanPhase.RESEARCH, PlanPhase.PLANNING, PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.RESEARCH: [PlanPhase.PLANNING, PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.PLANNING: [PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.ORCHESTRATE: [PlanPhase.ASSEMBLY],
    PlanPhase.ASSEMBLY: [],
}

PHASE_DISPLAY_NAMES: Dict[PlanPhase, str] = {
    PlanPhase.CONTEXT: "Context Collection",
    PlanPhase.RESEARCH: "Research",
    PlanPhase.PLANNING: "Planning",
    PlanPhase.ORCHESTRATE: "Execution",
    PlanPhase.ASSEMBLY: "Assembly",
}

# ---------------------------------------------------------------------------
# Per-phase progress step dictionaries (Req 16)
#
# Each dict maps step names to a progress fraction within that phase.
# Values are monotonically non-decreasing in insertion order, start at 0.0,
# and end in [0.95, 1.0].
# ---------------------------------------------------------------------------

CONTEXT_PROGRESS: Dict[str, float] = {
    "validate_context": 0.0,
    "collect_context": 0.25,
    "review": 0.50,
    "deep_analysis": 0.75,
    "feedback_review": 0.90,
    "complete": 1.0,
}

RESEARCH_PROGRESS: Dict[str, float] = {
    "formulate_queries": 0.0,
    "dispatch_research": 0.50,
    "aggregate": 0.65,
    "gap_check": 0.75,
    "confidence_gate": 0.85,
    "approval": 1.00,
}

# Backward-compatible alias — existing code imports this name.
RESEARCH_NODE_PROGRESS = RESEARCH_PROGRESS

PLANNING_PROGRESS: Dict[str, float] = {
    "roadmap": 0.0,
    "feasibility": 0.15,
    "decompose": 0.30,
    "validate_dag": 0.50,
    "assign": 0.65,
    "align": 0.80,
    "approval": 1.0,
}

ORCHESTRATE_PROGRESS: Dict[str, float] = {
    "budget_check": 0.0,
    "task_selector": 0.0,
    "fetch_context": 0.15,
    "gap": 0.25,
    "task_context_input": 0.25,
    "task_research": 0.30,
    "tool_plan": 0.35,
    "dispatch": 0.45,
    "worker": 0.60,
    "critique": 0.80,
    "prune_after_orchestrate": 1.0,
    "progress": 1.0,
}

ASSEMBLY_PROGRESS: Dict[str, float] = {
    "completeness": 0.0,
    "template": 0.15,
    "generate": 0.35,
    "consistency": 0.55,
    "composition_review": 0.60,
    "assemble": 0.70,
    "validate": 0.85,
    "approval": 1.0,
    "finalize": 1.0,
}

PHASE_PROGRESS: Dict[str, Dict[str, float]] = {
    "context": CONTEXT_PROGRESS,
    "research": RESEARCH_PROGRESS,
    "planning": PLANNING_PROGRESS,
    "orchestrate": ORCHESTRATE_PROGRESS,
    "assembly": ASSEMBLY_PROGRESS,
}
