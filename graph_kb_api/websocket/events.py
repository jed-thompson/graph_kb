"""
Pydantic event models for the unified spec wizard WebSocket protocol.

Mirrors the shared TypeScript schema in shared/websocket-events.ts.
Used for validating incoming payloads and serializing outgoing events.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# ── Shared Types ─────────────────────────────────────────────────


class PhaseId(str, Enum):
    """Workflow phase identifiers for the spec and plan wizards.

    Spec phases: context → review → research → plan → orchestrate → completeness → generate
    Plan-specific phases: planning, assembly
    """

    CONTEXT = "context"
    REVIEW = "review"
    RESEARCH = "research"
    PLAN = "plan"
    ORCHESTRATE = "orchestrate"
    COMPLETENESS = "completeness"
    GENERATE = "generate"
    PLANNING = "planning"
    ASSEMBLY = "assembly"


class PhaseField(BaseModel):
    """Describes a single input field presented to the user during a phase prompt."""

    id: str
    label: str
    type: str  # "text" | "textarea" | "select" | "file" | "multiselect" | "json"
    required: bool
    options: Optional[List[Union[str, Dict[str, str]]]] = None
    placeholder: Optional[str] = None


# ── Client → Server Payloads ─────────────────────────────────────


class SpecStartPayload(BaseModel):
    """Payload for spec.start — initiates a new wizard session."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class SpecPhaseInputPayload(BaseModel):
    """Payload for spec.phase.input — submits user data for a phase."""

    session_id: str = Field(..., min_length=1)
    phase: PhaseId
    data: Dict[str, Any] = Field(default_factory=dict)


class SpecNavigatePayload(BaseModel):
    """Payload for spec.navigate — requests backward navigation to a target phase."""

    session_id: str = Field(..., min_length=1)
    target_phase: PhaseId
    confirm_cascade: bool = False


# ── Server → Client Data Models ──────────────────────────────────


class SpecPhasePromptData(BaseModel):
    """Data for spec.phase.prompt — tells the client which fields to render."""

    session_id: str
    phase: PhaseId
    fields: List[PhaseField]
    prefilled: Optional[Dict[str, Any]] = None
    agent_content: Optional[str] = None
    context_documents: Optional[List[Dict[str, Any]]] = None
    context_items: Optional[Dict[str, Any]] = None
    artifacts: Optional[List[Dict[str, Any]]] = None
    budget: Optional[Dict[str, Any]] = None


class SpecPhaseProgressData(BaseModel):
    """Data for spec.phase.progress — streams agent progress to the client."""

    session_id: str
    phase: PhaseId
    message: str
    percent: float = Field(..., ge=0.0, le=1.0)
    agent_content: Optional[str] = None


class SpecPhaseCompleteData(BaseModel):
    """Data for spec.phase.complete — signals a phase finished with its result."""

    session_id: str
    phase: PhaseId
    result: Dict[str, Any]


class SpecErrorData(BaseModel):
    """Data for spec.error — reports an error to the client."""

    message: str
    code: str
    phase: Optional[PhaseId] = None


class SpecCompleteData(BaseModel):
    """Data for spec.complete — signals the entire workflow finished successfully."""

    session_id: str
    spec_document_url: str
    story_cards_url: Optional[str] = None


# ── Plan Navigation Data Models ──────────────────────────────────


class PlanStateData(BaseModel):
    """Data for plan.state — full workflow snapshot for UI reconstruction."""

    session_id: str
    workflow_status: str
    current_phase: Optional[str] = None
    completed_phases: Dict[str, bool] = {}
    budget: Dict[str, Any] = {}
    phase_summaries: Optional[Dict[str, Dict[str, Any]]] = None


class PlanCascadeConfirmData(BaseModel):
    """Data for plan.cascade.confirm — ask user to confirm cascade re-run."""

    session_id: str
    target_phase: str
    affected_phases: List[str] = []
    estimated_llm_calls: int = 0
    dirty_phases: List[str] = []


# ── Review Analysis Data Models ──────────────────────────────────


class DocumentCommentData(BaseModel):
    """A single inline comment on a document or field from review analysis."""

    target_id: str
    target_type: str = Field(..., pattern=r"^(field|document|section)$")
    comment: str
    severity: str = Field(..., pattern=r"^(info|warning|error)$")
    suggestion: Optional[str] = None


class KnowledgeGapData(BaseModel):
    """An identified gap in the specification."""

    id: str
    category: str = Field(..., pattern=r"^(scope|technical|constraint|stakeholder)$")
    title: str
    description: str
    impact: str = Field(..., pattern=r"^(high|medium|low)$")
    questions: List[str] = Field(default_factory=list)
    suggested_answers: List[str] = Field(default_factory=list)


class SpecReviewResultData(BaseModel):
    """Complete review analysis result from ContextReviewAgent."""

    completeness_score: float = Field(..., ge=0.0, le=1.0)
    document_comments: List[DocumentCommentData] = Field(default_factory=list)
    gaps: List[KnowledgeGapData] = Field(default_factory=list)
    suggested_actions: List[str] = Field(default_factory=list)
    summary: str = ""
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)


# ── Progress Emission Helper ──────────────────────────────────────

# Global reference to WebSocket manager, set by dispatcher at startup
_ws_manager: Optional[Any] = None


def set_ws_manager(manager: Any) -> None:
    """Set the WebSocket manager reference for progress emission."""
    global _ws_manager
    _ws_manager = manager


async def emit_phase_progress(
    session_id: str,
    phase: PhaseId,
    step: str,
    message: str,
    progress_pct: float,
    client_id: Optional[str] = None,
) -> None:
    """Emit a spec.phase.progress event.

    This is a fire-and-forget helper that safely emits progress
    without blocking phase execution. If no WebSocket manager is
    available, it logs a warning and returns.

    Args:
        session_id: The workflow/session ID
        phase: Current phase name (context, research, plan, etc.)
        step: Current step within the phase
        message: Human-readable progress message
        progress_pct: Progress percentage (0.0 to 1.0)
        client_id: Optional client ID for direct WebSocket emission
    """
    import logging

    logger = logging.getLogger(__name__)

    if _ws_manager is None:
        logger.debug(f"Progress: [{phase}] {step} - {message} ({progress_pct * 100:.0f}%)")
        return

    try:
        serialized = SpecPhaseProgressData(
            session_id=session_id,
            phase=phase,
            message=f"{step}: {message}",
            percent=progress_pct,
        )

        # If client_id is provided, emit directly
        if client_id:
            await _ws_manager.send_event(
                client_id=client_id,
                event_type="spec.phase.progress",
                workflow_id=session_id,
                data=serialized.model_dump(),
            )
        else:
            # Broadcast to all clients watching this session
            await _ws_manager.broadcast_to_session(
                session_id=session_id,
                event_type="spec.phase.progress",
                data=serialized.model_dump(),
            )
    except Exception as e:
        logger.warning(f"Failed to emit progress: {e}")
