"""
WebSocket workflow handlers package.

Provides handlers for ask-code, ingest, multi_agent, deep, and plan
workflows over WebSocket. Supports start, input, cancel, reconnect, and action
message types.
"""

from graph_kb_api.websocket.handlers.ask_code import handle_ask_code_workflow
from graph_kb_api.websocket.handlers.base import (
    ASK_CODE_NODE_PHASES,
    DEEP_AGENT_NODE_PHASES,
    MULTI_AGENT_NODE_PHASES,
    _debug_log,
    logger,
)
from graph_kb_api.websocket.handlers.deep_agent import handle_deep_agent_workflow
from graph_kb_api.websocket.handlers.dispatcher import (
    dispatch_message,
    process_message,
)
from graph_kb_api.websocket.handlers.ingest import handle_ingest_workflow
from graph_kb_api.websocket.handlers.multi_agent import handle_multi_agent_workflow
from graph_kb_api.websocket.handlers.research_dispatcher import (
    dispatch_research_message,
    handle_research_gap_answer,
    handle_research_review_start,
    handle_research_start,
)
from graph_kb_api.websocket.manager import manager

__all__ = [
    # Public API
    "process_message",
    "dispatch_message",
    # Workflow handlers
    "handle_ask_code_workflow",
    "handle_deep_agent_workflow",
    "handle_multi_agent_workflow",
    "handle_ingest_workflow",
    # Research handlers
    "handle_research_start",
    "handle_research_review_start",
    "handle_research_gap_answer",
    "dispatch_research_message",
    # Shared exports
    "manager",
    "logger",
    "_debug_log",
    "ASK_CODE_NODE_PHASES",
    "DEEP_AGENT_NODE_PHASES",
    "MULTI_AGENT_NODE_PHASES",
]
