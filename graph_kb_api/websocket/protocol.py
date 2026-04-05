"""
WebSocket message protocol.

Defines Pydantic models for client-server communication.
Uses the canonical schemas from graph_kb_api.schemas.websocket
and adds protocol-level models for routing and workflow payloads.
"""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

# Re-export canonical schemas for convenience
from graph_kb_api.schemas.websocket import (
    VALID_WORKFLOW_TYPES,
    WSInputPayload,
    WSMessage,
    WSOutgoingMessage,
    WSStartPayload,
)

# Valid outgoing message types
VALID_OUTGOING_TYPES = {"partial", "complete", "error", "progress", "preview"}

# Valid input decisions
VALID_DECISIONS = {"proceed", "configure", "cancel"}

# Valid action values
VALID_ACTIONS = {"pause", "resume"}


# Extended client message types (superset of WSMessage to include reconnect/action)


class ClientMessage(BaseModel):
    """Union type for all client messages including reconnect, action, and plan wizard messages."""

    type: str  # Allows "start", "input", "cancel", "reconnect", "action", and "plan.*" messages
    payload: Dict[str, Any] = Field(default_factory=dict)
    workflow_id: Optional[str] = None


# Workflow-Specific Payloads


class AskCodePayload(BaseModel):
    """Payload for ask-code workflow."""

    query: str
    repo_id: str
    conversation_id: Optional[str] = None


class IngestPayload(BaseModel):
    """Payload for ingest workflow."""

    git_url: str
    branch: str = "main"
    force_reindex: bool = False
    resume: bool = False  # Resume interrupted ingestion


class DiffPayload(BaseModel):
    """Payload for diff workflow."""

    repo_id: str
    from_commit: str
    to_commit: Optional[str] = None


class DeepAgentPayload(BaseModel):
    """Payload for deep agent workflow."""

    query: str
    repo_id: str
    conversation_id: Optional[str] = None


class MultiAgentPayload(BaseModel):
    """Payload for multi-agent workflow."""

    query: str
    template_id: Optional[str] = None
    template_vars: Optional[Dict[str, Any]] = None
    repo_id: Optional[str] = None
    conversation_id: Optional[str] = None
    max_agents: Optional[int] = None
    auto_review: bool = True


class ReconnectPayload(BaseModel):
    """Payload for reconnect message."""

    workflow_id: str
    last_event_id: Optional[str] = None


class ActionPayload(BaseModel):
    """Payload for action message (pause/resume ingestion)."""

    workflow_id: str
    action: Literal["pause", "resume"]


class CancelPayload(BaseModel):
    """Payload for cancel message."""

    workflow_id: str


def build_outgoing_message(
    msg_type: Literal["partial", "complete", "error", "progress", "preview"],
    data: Optional[Dict[str, Any]] = None,
    agent: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a validated outgoing message dict.

    Args:
        msg_type: One of partial, complete, error, progress, preview.
        data: Message payload.
        agent: Optional agent identifier for multi-agent partial results.

    Returns:
        Dict suitable for sending via WebSocket.
    """
    msg = WSOutgoingMessage(
        type=msg_type,
        data=data or {},
        agent=agent,
    )
    return msg.model_dump(exclude_none=True)
