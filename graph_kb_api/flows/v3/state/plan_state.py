from __future__ import annotations

"""PlanState schema for the /plan command built on LangGraph."""

import operator
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
    context_items: NotRequired[Dict[str, Any]]
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
    context_items: Dict[str, Any]
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


class PlanState(TypedDict):
    """Consolidated state for the /plan command with hybrid storage."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    context: Annotated[ContextData, operator.or_]
    review: Annotated[ReviewData, operator.or_]
    research: Annotated[ResearchData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    orchestrate: Annotated[OrchestrateData, operator.or_]
    completeness: Annotated[CompletenessData, operator.or_]
    generate: Annotated[GenerateData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    # Multi-document manifest (top-level so it survives prune nodes
    # and is accessible across orchestrate + assembly subgraphs).
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    # Re-orchestration flags (set by CompositionReviewNode, consumed by PlanEngine).
    needs_re_orchestrate: NotRequired[bool]
    re_execute_task_ids: NotRequired[list[str]]
    re_orchestration_count: NotRequired[int]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    error: NotRequired[Dict[str, Any]]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class ContextSubgraphState(TypedDict):
    """State for the context subgraph."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    context: Annotated[ContextData, operator.or_]
    review: Annotated[ReviewData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class ResearchSubgraphState(TypedDict):
    """State for the research subgraph."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    context: Annotated[ContextData, operator.or_]  # For FormulateQueriesNode, GapCheckNode
    review: Annotated[ReviewData, operator.or_]  # For ReviewNode, DeepAnalysisNode
    research: Annotated[ResearchData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class PlanningSubgraphState(TypedDict):
    """State for the planning subgraph."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    context: Annotated[
        ContextData, operator.or_
    ]  # For RoadmapNode, FeasibilityNode, DecomposeNode, AlignNode, AssignNode
    research: Annotated[ResearchData, operator.or_]  # For all planning nodes
    plan: Annotated[PlanData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class OrchestrateSubgraphState(TypedDict):
    """State for the orchestrate subgraph."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    context: Annotated[ContextData, operator.or_]  # For FetchContextNode, TaskResearchNode
    research: Annotated[ResearchData, operator.or_]  # For TaskResearchNode, FetchContextNode
    orchestrate: Annotated[OrchestrateData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    # Multi-document manifest — must be present in subgraph state for
    # WorkerNode read-modify-write (LangGraph subgraph states are independent
    # schemas; keys not declared here are silently dropped from node outputs).
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    error: NotRequired[Dict[str, Any]]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


class AssemblySubgraphState(TypedDict):
    """State for the assembly subgraph."""

    artifacts: Annotated[Dict[str, ArtifactRef], operator.or_]
    budget: Annotated[BudgetState, _budget_reducer]
    transition_log: Annotated[List[TransitionEntry], _capped_list_add(50)]
    fingerprints: Annotated[Dict[str, PhaseFingerprint], operator.or_]
    orchestrate: Annotated[OrchestrateData, operator.or_]
    plan: Annotated[PlanData, operator.or_]
    context: Annotated[ContextData, operator.or_]
    research: Annotated[ResearchData, operator.or_]
    completeness: Annotated[CompletenessData, operator.or_]
    generate: Annotated[GenerateData, operator.or_]
    completed_phases: Annotated[Dict[str, bool], _last_write_wins]
    # Multi-document manifest — must be present so GenerateNode, CompositionReviewNode,
    # AssembleNode, and FinalizeNode can read/write manifest entries within this subgraph.
    document_manifest: Annotated[DocumentManifest | None, _manifest_reducer]
    # Re-orchestration flags (set by CompositionReviewNode, consumed by PlanEngine).
    needs_re_orchestrate: NotRequired[bool]
    re_execute_task_ids: NotRequired[list[str]]
    re_orchestration_count: NotRequired[int]
    session_id: NotRequired[str]
    workflow_status: Annotated[Literal["idle", "running", "paused", "completed", "error", "budget_exhausted", "rejected"], _workflow_status_reducer]
    paused_phase: NotRequired[str]
    navigation: NavigationState
    messages: Annotated[list, add_messages]


CASCADE_MAP: Dict[PlanPhase, List[PlanPhase]] = {
    PlanPhase.CONTEXT: [PlanPhase.RESEARCH, PlanPhase.PLANNING, PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.RESEARCH: [PlanPhase.PLANNING, PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.PLANNING: [PlanPhase.ORCHESTRATE, PlanPhase.ASSEMBLY],
    PlanPhase.ORCHESTRATE: [PlanPhase.ASSEMBLY],
    PlanPhase.ASSEMBLY: [],
}

PHASE_WEIGHTS: Dict[PlanPhase, float] = {
    PlanPhase.CONTEXT: 0.05,
    PlanPhase.RESEARCH: 0.15,
    PlanPhase.PLANNING: 0.10,
    PlanPhase.ORCHESTRATE: 0.50,
    PlanPhase.ASSEMBLY: 0.20,
}

RESEARCH_NODE_PROGRESS: Dict[str, float] = {
    "formulate_queries": 0.0,
    "dispatch_research": 0.50,
    "aggregate": 0.65,
    "gap_check": 0.75,
    "confidence_gate": 0.85,
    "approval": 1.00,
}

assert abs(sum(PHASE_WEIGHTS.values()) - 1.0) < 1e-9, (
    f"PHASE_WEIGHTS must sum to 1.0, got {sum(PHASE_WEIGHTS.values())}"
)
