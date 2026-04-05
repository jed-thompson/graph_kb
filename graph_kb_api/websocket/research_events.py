"""
Pydantic event models for the /research WebSocket protocol.

Provides event models for standalone research context gathering with
repository selection, web URL fetching, and document processing.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Research Start Payload ─────────────────────────────────────────


class ResearchStartPayload(BaseModel):
    """Payload for research.start — initiates a new research session."""

    repo_id: str = Field(..., min_length=1, description="Repository ID to research")
    web_urls: List[str] = Field(default_factory=list, description="Web URLs to fetch")
    document_ids: List[str] = Field(default_factory=list, description="Uploaded document IDs")
    query: Optional[str] = Field(None, description="Optional research query focus")


# ── Research Review Payload ────────────────────────────────────────


class ResearchReviewStartPayload(BaseModel):
    """Payload for research.review.start — triggers LLM review of gathered context."""

    session_id: str = Field(..., min_length=1)
    focus_areas: Optional[List[str]] = None


class ResearchGapAnswerPayload(BaseModel):
    """Payload for research.gap.answer — submits answer to a knowledge gap."""

    session_id: str = Field(..., min_length=1)
    gap_id: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)


class ResearchReviewCompletePayload(BaseModel):
    """Payload for research.review.complete — result of LLM review."""

    session_id: str = Field(..., min_length=1)
    review_result: "ResearchReviewResult"


# ── Research Context Card Model ────────────────────────────────────


class ResearchContextCard(BaseModel):
    """A single context card with mermaid-enabled content."""

    id: str
    source_type: str = Field(..., description="web, document, repository, generated")
    source_url: Optional[str] = None
    source_name: str
    title: str
    content: str = Field(..., description="Markdown content with possible mermaid diagrams")
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    created_at: str


class ResearchGap(BaseModel):
    """A detected knowledge gap requiring user input."""

    id: str
    category: str = Field(..., description="scope, technical, constraint, stakeholder")
    question: str
    context: str
    suggested_answers: List[str] = Field(default_factory=list)
    impact: str = Field(..., description="high, medium, low")


class ResearchRisk(BaseModel):
    """A detected risk in the research."""

    id: str
    category: str = Field(..., description="technical, timeline, resource, dependency")
    description: str
    severity: str = Field(..., description="critical, high, medium, low")
    mitigation: str


class ResearchFindings(BaseModel):
    """Aggregated research findings."""

    summary: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    key_insights: List[str] = Field(default_factory=list)
    related_modules: List[Dict[str, str]] = Field(default_factory=list)
    risks: List[ResearchRisk] = Field(default_factory=list)


class ResearchReviewResult(BaseModel):
    """Result of LLM review of gathered context."""

    id: str
    summary: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    overall_assessment: str = Field(
        ...,
        description="excellent, good, adequate, needs_improvement"
    )
    reviewed_at: str


# ── Event Emission Helpers ─────────────────────────────────────────

# Global reference to WebSocket manager, set by dispatcher at startup
_research_ws_manager: Optional[Any] = None


def set_research_ws_manager(manager: Any) -> None:
    """Set the WebSocket manager reference for research progress emission."""
    global _research_ws_manager
    _research_ws_manager = manager


async def _emit_event(
    event_type: str,
    session_id: str,
    data: Dict[str, Any],
    client_id: Optional[str] = None,
) -> None:
    """Internal fire-and-forget event emitter."""
    if _research_ws_manager is None:
        logger.debug(
            "Research event (no ws): %s session=%s data=%s",
            event_type,
            session_id,
            data,
        )
        return

    try:
        if client_id:
            await _research_ws_manager.send_event(
                client_id=client_id,
                event_type=event_type,
                workflow_id=session_id,
                data=data,
            )
        else:
            logger.warning("No client_id for research event %s, dropping", event_type)
    except Exception as e:
        logger.warning("Failed to emit %s: %s", event_type, e)


async def emit_research_started(
    session_id: str,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.started when session is created."""
    await _emit_event(
        "research.started",
        session_id,
        {"session_id": session_id},
        client_id,
    )


async def emit_research_progress(
    session_id: str,
    phase: str,
    message: str,
    percent: float,
    client_id: Optional[str] = None,
    *,
    step: Optional[str] = None,
) -> None:
    """Emit research.progress with phase and step information."""
    data: Dict[str, Any] = {
        "session_id": session_id,
        "phase": phase,
        "message": message,
        "percent": percent,
    }
    if step:
        data["step"] = step
    await _emit_event("research.progress", session_id, data, client_id)


async def emit_context_found(
    session_id: str,
    context_card: ResearchContextCard,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.context.found when new context is discovered."""
    await _emit_event(
        "research.context.found",
        session_id,
        {"session_id": session_id, "context_card": context_card.model_dump()},
        client_id,
    )


async def emit_url_fetched(
    session_id: str,
    url: str,
    summary: Optional[str],
    success: bool,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.url.fetched when a web URL is processed."""
    await _emit_event(
        "research.url.fetched",
        session_id,
        {
            "session_id": session_id,
            "url": url,
            "summary": summary,
            "success": success,
        },
        client_id,
    )


async def emit_document_processed(
    session_id: str,
    document_id: str,
    filename: str,
    summary: Optional[str],
    client_id: Optional[str] = None,
) -> None:
    """Emit research.document.processed when a document is analyzed."""
    await _emit_event(
        "research.document.processed",
        session_id,
        {
            "session_id": session_id,
            "document_id": document_id,
            "filename": filename,
            "summary": summary,
        },
        client_id,
    )


async def emit_gap_detected(
    session_id: str,
    gap: ResearchGap,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.gap.detected when a knowledge gap is found."""
    await _emit_event(
        "research.gap.detected",
        session_id,
        {"session_id": session_id, "gap": gap.model_dump()},
        client_id,
    )


async def emit_research_complete(
    session_id: str,
    findings: ResearchFindings,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.complete when research finishes."""
    await _emit_event(
        "research.complete",
        session_id,
        {"session_id": session_id, "findings": findings.model_dump()},
        client_id,
    )


async def emit_review_progress(
    session_id: str,
    message: str,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.review.progress during LLM review."""
    await _emit_event(
        "research.review.progress",
        session_id,
        {"session_id": session_id, "message": message},
        client_id,
    )


async def emit_review_complete(
    session_id: str,
    review_result: ResearchReviewResult,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.review.complete when LLM review finishes."""
    await _emit_event(
        "research.review.complete",
        session_id,
        {"session_id": session_id, "review_result": review_result.model_dump()},
        client_id,
    )


async def emit_research_error(
    session_id: str,
    message: str,
    code: str,
    client_id: Optional[str] = None,
) -> None:
    """Emit research.error on any workflow error."""
    await _emit_event(
        "research.error",
        session_id,
        {"session_id": session_id, "message": message, "code": code},
        client_id,
    )
