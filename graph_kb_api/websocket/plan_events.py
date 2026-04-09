"""
Pydantic event models for the /plan command WebSocket protocol.

   Extends the base spec wizard events with three-level progress hierarchy
(Phase → Step → Substep) and plan-specific payload models.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from graph_kb_api.flows.v3.state.plan_state import PHASE_WEIGHTS, DocumentManifest
from graph_kb_api.websocket.events import PhaseId

logger = logging.getLogger(__name__)

# Type alias for plan phase identifiers
PlanPhaseId = PhaseId


# ── Phase Prompt Type Detection ─────────────────────────────────────


class PhasePromptType(Enum):
    """Enum for phase prompt types used in interrupt handling."""

    FORM = "form"  # Default form-style prompt with fields
    APPROVAL = "approval"  # Approval decision with options
    PHASE_REVIEW = "phase_review"  # Phase completion review
    ANALYSIS_REVIEW = "analysis_review"  # Analysis/results review


@dataclass(frozen=True)
class PhasePromptState:
    """Structured result of phase prompt type detection.

    Provides both the enum type and convenience boolean flags for
    conditional logic in prompt handling.
    """

    prompt_type: PhasePromptType
    is_approval: bool
    is_phase_review: bool
    is_analysis_review: bool
    is_form: bool


def get_phase_prompt_state(data: Dict[str, Any]) -> PhasePromptState:
    """Determine the phase prompt type from interrupt data.

    Examines the ``type`` field in the data dict to classify the prompt
    and returns a structured state object with both the enum value and
    convenience boolean flags.

    Args:
        data: Interrupt/prompt data dict containing a ``type`` key.

    Returns:
        PhasePromptState with classified type and boolean flags.

    """
    prompt_type_str: Optional[str] = data.get("type")

    if prompt_type_str == PhasePromptType.APPROVAL.value:
        return PhasePromptState(
            prompt_type=PhasePromptType.APPROVAL,
            is_approval=True,
            is_phase_review=False,
            is_analysis_review=False,
            is_form=False,
        )
    elif prompt_type_str == PhasePromptType.PHASE_REVIEW.value:
        return PhasePromptState(
            prompt_type=PhasePromptType.PHASE_REVIEW,
            is_approval=False,
            is_phase_review=True,
            is_analysis_review=False,
            is_form=False,
        )
    elif prompt_type_str == PhasePromptType.ANALYSIS_REVIEW.value:
        return PhasePromptState(
            prompt_type=PhasePromptType.ANALYSIS_REVIEW,
            is_approval=False,
            is_phase_review=False,
            is_analysis_review=True,
            is_form=False,
        )
    else:
        return PhasePromptState(
            prompt_type=PhasePromptType.FORM,
            is_approval=False,
            is_phase_review=False,
            is_analysis_review=False,
            is_form=True,
        )


# ── Progress Data Model ──────────────────────────────────────────


class SubgraphProgressData(BaseModel):
    """Extended progress event for subgraph-aware workflows.

    Provides three-level hierarchy: Phase → Step → Substep,
    plus optional fields for task-level visibility and budget tracking.
    """

    session_id: str
    phase: PlanPhaseId
    step: str
    message: str
    percent: float = Field(..., ge=0.0, le=1.0)
    substep: Optional[str] = None
    task_id: Optional[str] = None
    task_progress: Optional[str] = None
    iteration: Optional[int] = None
    max_iterations: Optional[int] = None
    agent_type: Optional[str] = None
    confidence: Optional[float] = None
    budget_remaining_pct: Optional[float] = None


# ── PlanDispatcher Payload Models ────────────────────────────────────────


class PlanStartPayload(BaseModel):
    """Payload for plan.start — initiates a new plan workflow session."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    max_llm_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    max_wall_clock_s: Optional[int] = None


class PlanPhaseInputPayload(BaseModel):
    """Payload for plan.phase.input — submits user data for a phase."""

    session_id: str = Field(..., min_length=1)
    phase: PlanPhaseId
    data: Dict[str, Any] = Field(default_factory=dict)


class PlanNavigatePayload(BaseModel):
    """Payload for plan.navigate — requests backward navigation to a target phase."""

    session_id: str = Field(..., min_length=1)
    target_phase: PlanPhaseId
    confirm_cascade: bool = False


class PlanResumePayload(BaseModel):
    """Payload for plan.resume — resumes a paused plan workflow.

    Supports optional budget limit overrides so users can increase
    budget limits and resume from the paused phase (Req 28.3).
    """

    session_id: str = Field(..., min_length=1)
    max_llm_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    max_wall_clock_s: Optional[int] = None


class PlanPausePayload(BaseModel):
    """Payload for plan.pause — pauses a running plan workflow."""

    session_id: str = Field(..., min_length=1)


class PlanCancelPayload(BaseModel):
    """Payload for plan.cancel — cancels and tears down an active plan session."""

    session_id: str = Field(..., min_length=1)


class PlanRetryPayload(BaseModel):
    """Payload for plan.retry — retries a failed phase."""

    session_id: str = Field(..., min_length=1)
    phase: Optional[PlanPhaseId] = None


class PlanStepForwardPayload(BaseModel):
    """Payload for plan.step.forward — advance to the next phase."""

    session_id: str = Field(..., min_length=1)


class PlanStepBackwardPayload(BaseModel):
    """Payload for plan.step.backward — navigate to a previous phase."""

    session_id: str = Field(..., min_length=1)
    target_phase: PlanPhaseId
    confirm_cascade: bool = False


class PlanReconnectPayload(BaseModel):
    """Payload for plan.reconnect — update client_id on WebSocket reconnect."""

    session_id: str = Field(..., min_length=1)


# ── Progress Emission Helper ─────────────────────────────────────

# Global reference to WebSocket manager, set by dispatcher at startup
_plan_ws_manager: Optional[Any] = None


def set_plan_ws_manager(manager: Any) -> None:
    """Set the WebSocket manager reference for plan progress emission."""
    global _plan_ws_manager
    _plan_ws_manager = manager


async def emit_phase_progress(
    session_id: str,
    phase: str,
    step: str,
    message: str,
    progress_pct: float,
    client_id: Optional[str] = None,
    *,
    substep: Optional[str] = None,
    task_id: Optional[str] = None,
    task_progress: Optional[str] = None,
    iteration: Optional[int] = None,
    max_iterations: Optional[int] = None,
    agent_type: Optional[str] = None,
    confidence: Optional[float] = None,
    agent_content: Optional[str] = None,
) -> None:
    """Emit a plan.phase.progress event with optional subgraph-level detail.

    This is a fire-and-forget helper that safely emits progress
    without blocking phase execution. Unset optional fields are omitted
    from the payload. If no WebSocket manager is available, it logs
    a debug message and returns.

    Args:
        session_id: The workflow/session ID.
        phase: Current phase name (context, research, planning, etc.).
        step: Current step within the phase.
        message: Human-readable progress message.
        progress_pct: Progress percentage (0.0 to 1.0).
        client_id: Optional client ID for direct WebSocket emission.
        substep: Optional detail within the step.
        task_id: Optional task identifier (orchestrate phase).
        task_progress: Optional task progress string (e.g. "3/8 tasks complete").
        iteration: Optional critique loop iteration number.
        max_iterations: Optional maximum iterations for critique loops.
        agent_type: Optional agent type executing the step.
        confidence: Optional current confidence score.
        agent_content: Optional rich markdown content for the frontend content panel.
    """
    if _plan_ws_manager is None:
        logger.debug(
            "Plan progress: [%s] %s - %s (%.0f%%)",
            phase,
            step,
            message,
            progress_pct * 100,
        )
        return

    try:
        progress_data: Dict[str, Any] = {
            "session_id": session_id,
            "phase": phase,
            "step": step,
            "message": message,
            "percent": max(0.0, min(1.0, progress_pct)),
        }
        # Only include optional fields when explicitly set (not None, not empty)
        if substep is not None:
            progress_data["substep"] = substep
        if task_id is not None:
            progress_data["task_id"] = task_id
        if task_progress is not None:
            progress_data["task_progress"] = task_progress
        if iteration is not None:
            progress_data["iteration"] = iteration
        if max_iterations is not None:
            progress_data["max_iterations"] = max_iterations
        if agent_type is not None:
            progress_data["agent_type"] = agent_type
        if confidence is not None:
            progress_data["confidence"] = confidence
        if agent_content is not None:
            progress_data["agentContent"] = agent_content

        if client_id:
            await _plan_ws_manager.send_event(
                client_id=client_id,
                event_type="plan.phase.progress",
                workflow_id=session_id,
                data=progress_data,
            )
        else:
            logger.warning("No client_id for plan progress, dropping")
            await _plan_ws_manager.broadcast_to_session(
                session_id=session_id,
                event_type="plan.phase.progress",
                data=progress_data,
            )

    except Exception as e:
        logger.warning("Failed to emit plan progress: %s", e)


# ── Extended Event Emission Helpers ───────────────────────────────


async def _emit_event(
    event_type: str,
    session_id: str,
    data: Dict[str, Any],
    client_id: Optional[str] = None,
) -> None:
    """Internal fire-and-forget event emitter.

    Sends via WebSocket manager if available, otherwise logs at debug level.
    Exceptions are caught and logged as warnings to avoid disrupting workflow.
    """
    if _plan_ws_manager is None:
        logger.debug(
            "Plan event (no ws): %s session=%s data=%s",
            event_type,
            session_id,
            data,
        )
        return

    try:
        if client_id:
            await _plan_ws_manager.send_event(
                client_id=client_id,
                event_type=event_type,
                workflow_id=session_id,
                data=data,
            )
        else:
            logger.warning("No client_id for plan event %s, dropping", event_type)
            await _plan_ws_manager.broadcast_to_session(
                session_id=session_id,
                event_type=event_type,
                data=data,
            )
    except Exception as e:
        logger.warning("Failed to emit %s: %s", event_type, e)


async def emit_phase_enter(
    session_id: str,
    phase: str,
    expected_steps: int,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.phase.enter`` when a subgraph begins execution."""
    await _emit_event(
        "plan.phase.enter",
        session_id,
        {"session_id": session_id, "phase": phase, "expected_steps": expected_steps},
        client_id,
    )


async def emit_phase_complete(
    session_id: str,
    phase: str,
    result_summary: str,
    duration_s: float,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.phase.complete`` when a subgraph exits successfully."""
    await _emit_event(
        "plan.phase.complete",
        session_id,
        {
            "session_id": session_id,
            "phase": phase,
            "result_summary": result_summary,
            "result": {"summary": result_summary, "duration_s": duration_s} if result_summary else None,
            "duration_s": duration_s,
        },
        client_id,
    )


async def emit_task_start(
    session_id: str,
    task_id: str,
    task_name: str,
    client_id: Optional[str] = None,
    *,
    spec_section: Optional[str] = None,
    spec_section_content: Optional[str] = None,
) -> None:
    """Emit ``plan.task.start`` when the orchestrate subgraph begins a task.

    Args:
        spec_section: Heading from the primary spec this task maps to (e.g. "5.3 Rates & Transit Times").
        spec_section_content: Truncated spec section text (~3K tokens) for frontend rendering.
    """
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "task_id": task_id,
        "task_name": task_name,
    }
    if spec_section is not None:
        payload["spec_section"] = spec_section
    if spec_section_content is not None:
        payload["spec_section_content"] = spec_section_content
    await _emit_event("plan.task.start", session_id, payload, client_id)


async def emit_task_critique(
    session_id: str,
    task_id: str,
    passed: bool,
    feedback: str,
    client_id: Optional[str] = None,
    *,
    task_name: Optional[str] = None,
    score: Optional[float] = None,
    iteration: Optional[int] = None,
) -> None:
    """Emit ``plan.task.critique`` after the architect critiques a task."""
    data: Dict[str, Any] = {
        "session_id": session_id,
        "task_id": task_id,
        "passed": passed,
        "feedback": feedback,
    }
    if task_name is not None:
        data["task_name"] = task_name
    if score is not None:
        data["score"] = score
    if iteration is not None:
        data["iteration"] = iteration
    await _emit_event(
        "plan.task.critique",
        session_id,
        data,
        client_id,
    )


async def emit_task_complete(
    session_id: str,
    task_id: str,
    client_id: Optional[str] = None,
    artifacts: Optional[list] = None,
    task_name: Optional[str] = None,
    spec_section: Optional[str] = None,
    approved: Optional[bool] = None,
) -> None:
    """Emit ``plan.task.complete`` when a task finishes in the orchestrate subgraph."""
    data: Dict[str, Any] = {"session_id": session_id, "task_id": task_id}
    if artifacts:
        data["artifacts"] = artifacts
    if task_name:
        data["task_name"] = task_name
    if spec_section:
        data["spec_section"] = spec_section
    if approved is not None:
        data["approved"] = approved
    await _emit_event(
        "plan.task.complete",
        session_id,
        data,
        client_id,
    )


async def emit_budget_warning(
    session_id: str,
    remaining_pct: float,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.budget.warning`` when budget drops below 15%."""
    await _emit_event(
        "plan.budget.warning",
        session_id,
        {
            "session_id": session_id,
            "budget_remaining_pct": remaining_pct,
            "message": f"Budget low: {remaining_pct * 100:.0f}% remaining",
        },
        client_id,
    )


async def emit_error(
    session_id: str,
    message: str,
    code: str,
    phase: Optional[str] = None,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.error`` on any workflow error.

    Requirement 21.7.
    """
    data: Dict[str, Any] = {
        "session_id": session_id,
        "message": message,
        "code": code,
    }
    if phase is not None:
        data["phase"] = phase
    await _emit_event("plan.error", session_id, data, client_id)


async def emit_circuit_breaker(
    session_id: str,
    message: str,
    total_tasks: int,
    rejected_count: int,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.circuit_breaker`` when all tasks fail critique in a full cycle.

    Signals to the frontend that orchestration has been stopped early because
    the input context is too thin for the agents to produce approved output.
    """
    await _emit_event(
        "plan.circuit_breaker",
        session_id,
        {
            "session_id": session_id,
            "message": message,
            "total_tasks": total_tasks,
            "rejected_count": rejected_count,
        },
        client_id,
    )


async def emit_manifest_update(
    session_id: str,
    manifest_entry: Dict[str, Any],
    total_documents: int,
    total_tokens: int,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.manifest.update`` when a new deliverable is added to the manifest.

    Provides progressive visibility into document production during orchestration,
    so the frontend can show what documents are being built in real time.
    """
    await _emit_event(
        "plan.manifest.update",
        session_id,
        {
            "session_id": session_id,
            "entry": manifest_entry,
            "total_documents": total_documents,
            "total_tokens": total_tokens,
        },
        client_id,
    )


async def emit_tasks_dag(
    session_id: str,
    tasks: list,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.tasks.dag`` with the full task list at orchestrate start.

    Sends every task (id, name, priority, dependencies) so the frontend can
    render all task cards upfront with pending status.
    """
    await _emit_event(
        "plan.tasks.dag",
        session_id,
        {
            "session_id": session_id,
            "tasks": tasks,
        },
        client_id,
    )


async def emit_complete(
    session_id: str,
    document_manifest: Optional[DocumentManifest] = None,
    spec_document_url: str = "",
    story_cards_url: Optional[str] = None,
    client_id: Optional[str] = None,
) -> None:
    """Emit ``plan.complete`` when the workflow finishes.

    Requirement 21.4. Updated to include document manifest for multi-doc output.

    Args:
        document_manifest: The full DocumentManifest TypedDict if available.
        spec_document_url: Legacy URL for the composed index (backward compat).
        story_cards_url: Unused — retained for backward compat.
        client_id: Optional WebSocket client ID.
    """
    data: Dict[str, Any] = {
        "session_id": session_id,
        "spec_document_url": spec_document_url,
    }
    if document_manifest:
        entries = document_manifest.get("entries", [])
        composed_index_ref = document_manifest.get("composed_index_ref")
        data["documentManifest"] = {
            "specName": document_manifest.get("spec_name", ""),
            "totalDocuments": document_manifest.get("total_documents", 0),
            "totalTokens": document_manifest.get("total_tokens", 0),
            "composedIndexUrl": composed_index_ref.get("key", "") if composed_index_ref else "",
            "entries": [
                {
                    "taskId": e.get("task_id", ""),
                    "specSection": e.get("spec_section", ""),
                    "downloadUrl": e.get("artifact_ref", {}).get("key", "") if e.get("artifact_ref") else "",
                    "status": e.get("status", "draft"),
                    "tokenCount": e.get("token_count", 0),
                    "filename": e.get("artifact_ref", {}).get("key", "").split("/")[-1]
                    if e.get("artifact_ref")
                    else "",
                    "sectionType": e.get("section_type", ""),
                    "errorMessage": e.get("error_message"),
                }
                for e in entries
            ],
        }
    if story_cards_url is not None:
        data["story_cards_url"] = story_cards_url
    await _emit_event("plan.complete", session_id, data, client_id)


# ── Progress Calculation ─────────────────────────────────────────


def calculate_overall_progress(
    completed_phases: Dict[str, bool],
    current_phase: str,
    current_phase_progress: float,
) -> float:
    """Compute overall progress as a weighted sum across subgraphs.

    Uses PHASE_WEIGHTS to assign each phase a proportion of the total
    progress bar. Completed phases contribute their full weight; the
    current active phase contributes proportionally.

    Args:
        completed_phases: Mapping of phase name to completion flag.
        current_phase: The phase currently executing.
        current_phase_progress: Progress within the current phase (0.0–1.0).

    Returns:
        Overall progress clamped to [0.0, 1.0].
    """
    total = 0.0
    for phase, weight in PHASE_WEIGHTS.items():
        if completed_phases.get(phase):
            total += weight
        elif phase == current_phase and current_phase_progress is not None:
            total += weight * max(0.0, min(1.0, current_phase_progress))
    return min(total, 1.0)
