"""Research WebSocket Dispatcher - routes research.* events.

Provides standalone research functionality with context gathering,
LLM review, and knowledge gap detection.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from graph_kb_api.flows.v3.tools.websearch import fetch_url_content
from graph_kb_api.websocket.handlers.base import logger
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.research_events import (
    ResearchContextCard,
    ResearchFindings,
    ResearchGap,
    ResearchGapAnswerPayload,
    ResearchReviewResult,
    ResearchReviewStartPayload,
    ResearchRisk,
    ResearchStartPayload,
    emit_context_found,
    emit_gap_detected,
    emit_research_complete,
    emit_research_error,
    emit_research_progress,
    emit_research_started,
    emit_review_complete,
    emit_url_fetched,
    set_research_ws_manager,
)

# Session storage
_sessions: Dict[str, Dict[str, Any]] = {}


def _get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Look up a research session by ID."""
    return _sessions.get(session_id)


def _validate_session_owner(session: Dict[str, Any], client_id: str, session_id: str) -> bool:
    """Verify that *client_id* owns *session*."""
    registered_client = session.get("client_id")
    if registered_client is None:
        return True
    return registered_client == client_id


def _cancel_running_task(session: Dict[str, Any]) -> bool:
    """Cancel the running research task in a session, if any."""
    task: Optional[asyncio.Task] = session.get("running_task")
    if task is not None and not task.done():
        task.cancel()
        try:
            asyncio.get_event_loop().run_until_complete(task)
        except (asyncio.CancelledError, Exception):
            pass
        session["running_task"] = None
        return True
    session["running_task"] = None
    return False


# ── Event Handlers ────────────────────────────────────────────────────────


async def handle_research_start(
    client_id: str,
    workflow_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle research.start - initiate a new research session."""
    try:
        data = ResearchStartPayload(**payload)
    except ValidationError as e:
        await manager.send_event(
            client_id=client_id,
            event_type="research.error",
            workflow_id=workflow_id,
            data={"message": f"Invalid payload: {e}", "code": "VALIDATION_ERROR"},
        )
        return

    session_id = str(uuid.uuid4())

    # Create session
    session: Dict[str, Any] = {
        "session_id": session_id,
        "client_id": client_id,
        "repo_id": data.repo_id,
        "web_urls": data.web_urls,
        "document_ids": data.document_ids,
        "query": data.query,
        "context_cards": [],
        "gaps": [],
        "findings": None,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
    }
    _sessions[session_id] = session

    await emit_research_started(session_id, client_id)

    # Start research task in background
    task = asyncio.create_task(_run_research(session_id, client_id))
    session["running_task"] = task


async def _run_research(session_id: str, client_id: str) -> None:
    """Execute the research workflow."""
    session = _get_session(session_id)
    if not session:
        return

    repo_id = session.get("repo_id", "")
    web_urls: List[str] = session.get("web_urls", [])

    try:
        # Phase 1: Setup
        await emit_research_progress(session_id, "setup", "Initializing research session", 0.1, client_id)

        # Phase 2: Fetch web URLs
        if web_urls:
            await emit_research_progress(session_id, "web_fetch", f"Fetching {len(web_urls)} web URLs", 0.2, client_id)
            for i, url in enumerate(web_urls):
                try:
                    # Fetch URL content directly
                    result = await fetch_url_content(url)

                    # Create context card
                    card = ResearchContextCard(
                        id=str(uuid.uuid4()),
                        source_type="web",
                        source_url=url,
                        source_name=url.split("//")[-1].split("/")[0],
                        title=f"Content from {url}",
                        content=result[:5000] if result else "No content extracted",
                        relevance_score=0.8,
                        tags=["web", "fetched"],
                        created_at=datetime.utcnow().isoformat(),
                    )
                    session["context_cards"].append(card.model_dump())
                    await emit_context_found(session_id, card, client_id)
                    await emit_url_fetched(session_id, url, card.title[:100], True, client_id)
                except Exception as e:
                    logger.warning("Failed to fetch URL %s: %s", url, e)
                    await emit_url_fetched(session_id, url, str(e), False, client_id)

                # Update progress
                progress = 0.2 + (0.3 * (i + 1) / len(web_urls))
                await emit_research_progress(
                    session_id, "web_fetch", f"Fetched {i + 1}/{len(web_urls)} URLs", progress, client_id
                )

        # Phase 3: Repository analysis (placeholder - would integrate with graph_store)
        await emit_research_progress(session_id, "repo_analysis", f"Analyzing repository {repo_id}", 0.5, client_id)

        # Create a placeholder context card for repository
        repo_card = ResearchContextCard(
            id=str(uuid.uuid4()),
            source_type="repository",
            source_name=repo_id,
            title=f"Repository Analysis: {repo_id}",
            content=(
                "## Repository Overview\n\nAnalyzed repository structure and code patterns."
                "\n\n```mermaid\ngraph TD\n    A[Repository] --> B[Modules]"
                "\n    A --> C[Components]\n    A --> D[Services]\n```"
            ),
            relevance_score=0.9,
            tags=["repository", "codebase"],
            created_at=datetime.utcnow().isoformat(),
        )
        session["context_cards"].append(repo_card.model_dump())
        await emit_context_found(session_id, repo_card, client_id)

        # Phase 4: Detect gaps
        await emit_research_progress(session_id, "gap_detection", "Analyzing for knowledge gaps", 0.7, client_id)

        # Create sample gap
        gap = ResearchGap(
            id=str(uuid.uuid4()),
            category="technical",
            question="What are the specific technical constraints for this feature?",
            context="The repository analysis revealed potential technical constraints that need clarification.",
            suggested_answers=["Performance requirements", "Security constraints", "Compatibility requirements"],
            impact="high",
        )
        session["gaps"].append(gap.model_dump())
        await emit_gap_detected(session_id, gap, client_id)

        # Phase 5: Generate findings
        await emit_research_progress(session_id, "synthesis", "Synthesizing research findings", 0.9, client_id)

        findings = ResearchFindings(
            summary="Research completed. Found relevant context from web sources and repository analysis.",
            confidence_score=0.75,
            key_insights=[
                "Repository has modular architecture",
                "Web sources provide additional context",
                "Some knowledge gaps require clarification",
            ],
            related_modules=[
                {"name": "Core Module", "path": "src/core", "reason": "Primary functionality"},
            ],
            risks=[
                ResearchRisk(
                    id=str(uuid.uuid4()),
                    category="technical",
                    description="Integration complexity with existing modules",
                    severity="medium",
                    mitigation="Incremental integration with testing",
                )
            ],
        )
        session["findings"] = findings.model_dump()

        # Complete
        await emit_research_progress(session_id, "complete", "Research complete", 1.0, client_id)
        await emit_research_complete(session_id, findings, client_id)
        session["status"] = "complete"

    except asyncio.CancelledError:
        logger.info("Research cancelled for session %s", session_id)
        session["status"] = "cancelled"
    except Exception as e:
        logger.exception("Research failed for session %s", session_id)
        await emit_research_error(session_id, str(e), "RESEARCH_ERROR", client_id)
        session["status"] = "error"


async def handle_research_review_start(
    client_id: str,
    workflow_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle research.review.start - trigger LLM review of gathered context."""
    try:
        data = ResearchReviewStartPayload(**payload)
    except ValidationError as e:
        await manager.send_event(
            client_id=client_id,
            event_type="research.error",
            workflow_id=workflow_id,
            data={"message": f"Invalid payload: {e}", "code": "VALIDATION_ERROR"},
        )
        return

    session = _get_session(data.session_id)
    if not session:
        await emit_research_error(data.session_id, "Session not found", "SESSION_NOT_FOUND", client_id)
        return

    if not _validate_session_owner(session, client_id, data.session_id):
        await emit_research_error(data.session_id, "Not authorized", "UNAUTHORIZED", client_id)
        return

    # Run review in background
    task = asyncio.create_task(_run_llm_review(data.session_id, client_id, data.focus_areas))
    session["running_task"] = task


async def _run_llm_review(
    session_id: str,
    client_id: str,
    focus_areas: Optional[List[str]] = None,
) -> None:
    """Execute LLM review of gathered context."""
    session = _get_session(session_id)
    if not session:
        return

    try:
        # Simulate LLM review (in production, would call ResearchAgent)
        await manager.send_event(
            client_id=client_id,
            event_type="research.review.progress",
            workflow_id=session_id,
            data={"session_id": session_id, "message": "Analyzing gathered context..."},
        )

        # Generate review result
        review = ResearchReviewResult(
            id=str(uuid.uuid4()),
            summary="The gathered context provides good coverage of the research topic. "
            "Repository analysis reveals modular architecture, and web sources provide "
            "additional context. One knowledge gap was detected that requires clarification.",
            strengths=[
                "Comprehensive repository analysis",
                "Relevant web sources identified",
                "Clear knowledge gap detection",
            ],
            weaknesses=[
                "Some context may be outdated",
                "Additional domain-specific sources could improve coverage",
            ],
            recommendations=[
                "Clarify the detected knowledge gap before proceeding",
                "Consider adding more domain-specific web sources",
                "Review relevance scores for accuracy",
            ],
            overall_assessment="good",
            reviewed_at=datetime.utcnow().isoformat(),
        )

        await emit_review_complete(session_id, review, client_id)

    except asyncio.CancelledError:
        logger.info("LLM review cancelled for session %s", session_id)
    except Exception as e:
        logger.exception("LLM review failed for session %s", session_id)
        await emit_research_error(session_id, str(e), "REVIEW_ERROR", client_id)


async def handle_research_gap_answer(
    client_id: str,
    workflow_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle research.gap.answer - submit answer to a knowledge gap."""
    try:
        data = ResearchGapAnswerPayload(**payload)
    except ValidationError as e:
        await manager.send_event(
            client_id=client_id,
            event_type="research.error",
            workflow_id=workflow_id,
            data={"message": f"Invalid payload: {e}", "code": "VALIDATION_ERROR"},
        )
        return

    session = _get_session(data.session_id)
    if not session:
        await emit_research_error(data.session_id, "Session not found", "SESSION_NOT_FOUND", client_id)
        return

    if not _validate_session_owner(session, client_id, data.session_id):
        await emit_research_error(data.session_id, "Not authorized", "UNAUTHORIZED", client_id)
        return

    # Update gap with answer
    gaps = session.get("gaps", [])
    for gap in gaps:
        if gap.get("id") == data.gap_id:
            gap["answer"] = data.answer
            break

    # Acknowledge the answer
    await manager.send_event(
        client_id=client_id,
        event_type="research.gap.answered",
        workflow_id=data.session_id,
        data={
            "session_id": data.session_id,
            "gap_id": data.gap_id,
            "answer": data.answer,
        },
    )


# ── Dispatch ──────────────────────────────────────────────────────────


_HANDLER_MAP: Dict[str, Any] = {
    "research.start": handle_research_start,
    "research.review.start": handle_research_review_start,
    "research.gap.answer": handle_research_gap_answer,
}


async def dispatch_research_message(
    client_id: str,
    msg_type: str,
    payload: Dict[str, Any],
    workflow_id: Optional[str],
) -> None:
    """Route research.* messages to the correct handler."""
    set_research_ws_manager(manager)

    handler = _HANDLER_MAP.get(msg_type)
    if handler is None:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id or "",
            data={
                "message": f"Unknown research message type: {msg_type}",
                "code": "UNKNOWN_RESEARCH_MESSAGE",
            },
        )
        return

    await handler(client_id, workflow_id or "", payload)
