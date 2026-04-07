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

from graph_kb_api.flows.v3.models.research_models import ResearchReviewResult
from graph_kb_api.websocket.handlers.base import logger
from graph_kb_api.websocket.handlers.multi_repo_orchestrator import MultiRepoOrchestrator
from graph_kb_api.websocket.handlers.research_runner import run_single_repo_research
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.research_events import (
    MultiRepoResearchStartPayload,
    ResearchGapAnswerPayload,
    ResearchHitlResponsePayload,
    ResearchReviewStartPayload,
    ResearchStartPayload,
    emit_research_error,
    emit_research_started,
    emit_review_complete,
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
    """Handle research.start — routes to single-repo or multi-repo flow."""
    # Multi-repo path: payload contains repo_ids (list)
    if "repo_ids" in payload:
        try:
            data = MultiRepoResearchStartPayload(**payload)
        except ValidationError as e:
            await manager.send_event(
                client_id=client_id,
                event_type="research.error",
                workflow_id=workflow_id,
                data={"message": f"Invalid payload: {e}", "code": "VALIDATION_ERROR"},
            )
            return
        await _run_multi_repo_research(client_id, workflow_id, data)
        return

    # Single-repo path (backward compat): payload contains repo_id (string)
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

    task = asyncio.create_task(run_single_repo_research(session, data.repo_id, client_id))
    session["running_task"] = task


async def _run_multi_repo_research(
    client_id: str,
    workflow_id: str,
    data: MultiRepoResearchStartPayload,
) -> None:
    """Route multi-repo research to the MultiRepoOrchestrator."""
    session_id = str(uuid.uuid4())

    # Deduplicate repo_ids
    repo_ids = list(dict.fromkeys(data.repo_ids))

    # Validate: all repos in relationships must be in repo_ids
    for rel in data.relationships:
        if rel.source_repo_id not in repo_ids or rel.target_repo_id not in repo_ids:
            await manager.send_event(
                client_id=client_id,
                event_type="research.error",
                workflow_id=workflow_id,
                data={
                    "message": (
                        f"Relationship references repo not in repo_ids: "
                        f"{rel.source_repo_id} -> {rel.target_repo_id}"
                    ),
                    "code": "VALIDATION_ERROR",
                },
            )
            return

    # Single-repo shortcut: no synthesis needed
    if len(repo_ids) == 1:
        session: Dict[str, Any] = {
            "session_id": session_id,
            "client_id": client_id,
            "repo_id": repo_ids[0],
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
        task = asyncio.create_task(run_single_repo_research(session, repo_ids[0], client_id))
        session["running_task"] = task
        return

    session = {
        "session_id": session_id,
        "client_id": client_id,
        "repo_ids": repo_ids,
        "relationships": [r.model_dump() for r in data.relationships],
        "strategy": data.strategy,
        "web_urls": data.web_urls,
        "document_ids": data.document_ids,
        "query": data.query,
        "context_cards": [],
        "gaps": [],
        "findings": None,
        "per_repo_findings": {},
        "hitl_events": {},
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
    }
    _sessions[session_id] = session

    await emit_research_started(session_id, client_id)

    orchestrator = MultiRepoOrchestrator(session, client_id)
    if data.strategy == "dependency_aware":
        task = asyncio.create_task(orchestrator.run_dependency_aware())
    else:
        task = asyncio.create_task(orchestrator.run_parallel_merge())
    session["running_task"] = task


async def handle_research_hitl_response(
    client_id: str,
    workflow_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle research.hitl.response — routes user decision back to waiting orchestrator."""
    try:
        data = ResearchHitlResponsePayload(**payload)
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
        return

    hitl_events: Dict[str, asyncio.Event] = session.get("hitl_events", {})
    # The orchestrator registers an event keyed by repo_id; we signal the latest one
    for event_obj in hitl_events.values():
        if not event_obj.is_set():
            session["hitl_choice"] = data.choice
            event_obj.set()
            break


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
    "research.hitl.response": handle_research_hitl_response,
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
