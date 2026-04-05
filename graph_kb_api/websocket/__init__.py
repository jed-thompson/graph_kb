"""
WebSocket module for Graph KB API.
"""

from graph_kb_api.schemas.websocket import (
    WSInputPayload,
    WSMessage,
    WSStartPayload,
)
from graph_kb_api.websocket.handlers import process_message
from graph_kb_api.websocket.manager import ConnectionManager, manager
from graph_kb_api.websocket.protocol import (
    VALID_ACTIONS,
    VALID_DECISIONS,
    VALID_OUTGOING_TYPES,
    VALID_WORKFLOW_TYPES,
    ClientMessage,
    WSOutgoingMessage,
)

__all__ = [
    "ConnectionManager",
    "manager",
    "process_message",
    "WSMessage",
    "WSStartPayload",
    "WSInputPayload",
    "WSOutgoingMessage",
    "ClientMessage",
    "VALID_WORKFLOW_TYPES",
    "VALID_OUTGOING_TYPES",
    "VALID_DECISIONS",
    "VALID_ACTIONS",
]
