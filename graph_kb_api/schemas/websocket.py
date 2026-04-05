"""
Pydantic schemas for WebSocket protocol messages.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, get_args

from pydantic import BaseModel, Field

WorkflowType = Literal["ask-code", "ingest", "multi_agent", "deep"]

VALID_WORKFLOW_TYPES: set[str] = set(get_args(WorkflowType))


class WSMessage(BaseModel):
    """Incoming WebSocket message."""

    type: Literal["start", "cancel", "input"]
    payload: Dict[str, Any] = Field(default_factory=dict)


class WSStartPayload(BaseModel):
    """Payload for a WebSocket start message."""

    workflow_type: WorkflowType
    repo_id: Optional[str] = None
    query: Optional[str] = None
    task: Optional[str] = None


class WSInputPayload(BaseModel):
    """Payload for a WebSocket input message.

    Supports both simple decision strings (for ask-code/ingest) and
    richer payloads for plan interrupt resume (clarification
    responses or approval decisions).
    """

    thread_id: str
    decision: Optional[str] = None
    # Plan clarification resume
    clarification_responses: Optional[Dict[str, str]] = None
    # Plan approval resume
    approved: Optional[bool] = None
    feedback: Optional[str] = None
    sections_to_revise: Optional[list] = None


class WSOutgoingMessage(BaseModel):
    """Outgoing WebSocket message from server."""

    type: Literal["partial", "complete", "error", "progress", "preview"]
    data: Optional[Dict[str, Any]] = None
    agent: Optional[str] = None
