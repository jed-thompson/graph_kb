"""
State schema for the Orchestrator subgraph.

This state is private to the orchestrator subgraph and transformed from/to
the parent workflow state by the OrchestratorNode wrapper.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional

from langgraph.types import Send
from typing_extensions import TypedDict


def _merge_dicts(left: dict, right: dict) -> dict:
    """Merge two dicts, with right taking precedence."""
    return {**left, **right}


# Route targets for orchestrator subgraph navigation
OrchestratorRouteTarget = Literal[
    # Internal node routing
    "context_fetch",
    "gap_checker",
    "tool_planner",
    "dispatcher",
    # Output routing (subgraph -> parent)
    "end",
    "gap_detector",
    "single",
    "parallel",
    "dispatch",
]


class OrchestratorSubgraphState(TypedDict):
    """Internal state schema for the orchestrator subgraph.

    Input keys (from parent):
        - todo_list, current_task_index, parallel_groups, completed_sections
        - is_rework, rework_count, max_reworks
        - review_feedback, clarification_responses, section_summaries
        - supplementary_docs, gaps_detected

    Internal flow keys:
        - ready_tasks: Tasks selected for dispatch
        - task_contexts: Retrieved context per task
        - context_gaps: Gaps detected during context retrieval
        - tool_assignments: Planned tools per task

    Output keys (to parent):
        - current_task: Single task for dispatch
        - assigned_agent: Agent type for single dispatch
        - agent_context: Context for the agent (includes review_feedback on rework)
        - sends: List of Send objects for parallel dispatch
        - awaiting_user_input: Whether user input is needed
        - route_to: See OrchestratorRouteTarget for valid values
    """

    # === Input from parent (preserved across nodes) ===
    todo_list: list[dict[str, Any]]
    current_task_index: int
    total_tasks: int
    parallel_groups: list[list[str]]
    completed_sections: dict[str, str]
    is_rework: bool
    rework_count: int
    max_reworks: int
    review_feedback: Optional[str]
    clarification_responses: Annotated[dict[str, Any], _merge_dicts]
    section_summaries: Annotated[dict[str, str], _merge_dicts]
    supplementary_docs: list[dict[str, Any]]
    gaps_detected: Annotated[dict[str, Any], _merge_dicts]
    progress_events: Annotated[list[dict[str, Any]], operator.add]

    # === Internal flow state (merged/accumulated) ===
    ready_tasks: list[dict[str, Any]]  # Replaced by task_selector
    task_contexts: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    context_gaps: list[dict[str, Any]]  # Replaced by gap_checker
    tool_assignments: Annotated[dict[str, list[str]], _merge_dicts]

    # === Output (set by dispatcher) ===
    current_task: Optional[dict[str, Any]]  # For single dispatch
    assigned_agent: str
    agent_context: Annotated[dict[str, Any], _merge_dicts]
    sends: Optional[list[Send]]  # For parallel dispatch
    awaiting_user_input: bool
    route_to: OrchestratorRouteTarget
