"""
WebSocket workflow handlers - Compatibility module.

This module re-exports all handlers from the handlers/ package for backward
compatibility. New code should import directly from graph_kb_api.websocket.handlers.
"""

# Re-export everything from the handlers package
from graph_kb_api.websocket.handlers import (
    ASK_CODE_NODE_PHASES,
    DEEP_AGENT_NODE_PHASES,
    MULTI_AGENT_NODE_PHASES,
    _debug_log,
    dispatch_message,
    # Workflow handlers
    handle_ask_code_workflow,
    handle_deep_agent_workflow,
    handle_ingest_workflow,
    handle_multi_agent_workflow,
    logger,
    # Shared exports
    manager,
    # Dispatcher
    process_message,
)

__all__ = [
    "process_message",
    "dispatch_message",
    "handle_ask_code_workflow",
    "handle_deep_agent_workflow",
    "handle_multi_agent_workflow",
    "handle_ingest_workflow",
    "manager",
    "logger",
    "_debug_log",
    "ASK_CODE_NODE_PHASES",
    "DEEP_AGENT_NODE_PHASES",
    "MULTI_AGENT_NODE_PHASES",
]
