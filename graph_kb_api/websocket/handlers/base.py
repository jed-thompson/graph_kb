"""
Shared utilities and constants for WebSocket workflow handlers.

Contains node-to-phase maps, debug logging, and common imports.
"""

import os
from typing import Dict

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

# Enable verbose debug logging for WebSocket workflows
_WS_DEBUG = os.environ.get("WS_DEBUG", "true").lower() in ("true", "1", "yes")


def _debug_log(message: str, **kwargs) -> None:
    """Log debug message if WS_DEBUG is enabled."""
    if _WS_DEBUG:
        logger.info(f"[WS-DEBUG] {message}", data=kwargs if kwargs else None)


# ---------------------------------------------------------------------------
# Node-to-phase maps for LangGraph workflow streaming progress
# Keys are the actual node names from each workflow's _compile_workflow().
# Values are human-readable phase strings sent to the frontend.
# ---------------------------------------------------------------------------

# AskCode — linear with bounded agent loop (agent → tools → agent)
ASK_CODE_NODE_PHASES: Dict[str, str] = {
    "validate": "validating",
    "analyze_question": "analyzing",
    "clarify": "clarifying",
    "retrieve": "retrieving",
    "graph_expansion": "expanding",
    "agent": "reasoning",
    "tools": "executing_tools",
    "format": "formatting",
    "present": "presenting",
}

# DeepAgent — linear, no loops
DEEP_AGENT_NODE_PHASES: Dict[str, str] = {
    "validate": "validating",
    "determine_repo": "determining_repo",
    "deep_agent": "reasoning",
    "present": "presenting",
}

# MultiAgent — has cycles, MUST use indeterminate progress
MULTI_AGENT_NODE_PHASES: Dict[str, str] = {
    "input_prepare": "preparing",
    "task_breakdown": "breaking_down",
    "task_classifier": "classifying",
    "agent_coordinator": "coordinating",
    "tool_selector": "selecting_tools",
    "multi_pass_review": "reviewing",
    "quality_check": "checking_quality",
    "reprompt_agent": "reprompting",
    "result_aggregation": "aggregating",
    "clarification": "clarifying",
}
