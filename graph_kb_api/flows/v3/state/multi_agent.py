from __future__ import annotations

"""
Multi-agent state schema for LangGraph v3 workflows.

Defines the state structure for the multi-agent workflow system.
"""

import operator
from typing import Annotated, Any, Dict, List, Literal

from langgraph.graph import add_messages
from typing_extensions import NotRequired, TypedDict

from graph_kb_api.flows.v3.state.common import BaseCommandState


class MultiAgentState(BaseCommandState, TypedDict):
    """
    State for multi-agent workflow system.

    Extends BaseCommandState with fields for:
    - Task breakdown and classification
    - Agent execution and coordination
    - Tool assignment and results
    - Multi-pass review pipeline
    - Result aggregation and formatting
    """

    # ── Input (additional) ──
    user_input: str
    template_id: NotRequired[str]
    template_vars: NotRequired[Dict[str, Any]]

    # ── Task breakdown ──
    primary_task: NotRequired[Dict[str, Any]]
    sub_tasks: Annotated[List[Dict[str, Any]], operator.add]
    task_dependencies: Annotated[List[Dict[str, Any]], operator.add]

    # ── Agent assignment ──
    agent_assignments: Annotated[List[Dict[str, Any]], operator.add]
    agent_status: Annotated[Dict[str, str], operator.or_]

    # ── Tool assignment ──
    tool_assignments: Annotated[Dict[str, List[str]], operator.or_]

    # ── Agent execution ──
    agent_outputs: Annotated[Dict[str, Dict[str, Any]], operator.or_]
    agent_tokens_used: Annotated[Dict[str, int], operator.or_]

    # ── Review process ──
    review_stage: Literal["none", "completion", "quality", "security", "final"]
    review_passes: Annotated[List[Dict[str, Any]], operator.add]
    review_failures: Annotated[List[Dict[str, Any]], operator.add]
    reprompt_attempts: int
    max_reprompts: int

    # ── Output ──
    aggregated_results: NotRequired[Dict[str, Any]]
    formatted_output: NotRequired[str]

    # ── Messages ──
    messages: Annotated[list, add_messages]

    # ── Clarification ──
    awaiting_clarification: bool
    clarification_questions: NotRequired[List[str]]
    clarification_responses: Annotated[List[str], operator.add]
