"""
Base state schema for LangGraph v3 workflows.

This module defines the base state structure that all command workflows extend from.
It includes proper type annotations and reducer functions for state accumulation.
"""

import operator
from typing import Annotated, Any, List

from typing_extensions import NotRequired, TypedDict


class BaseCommandState(TypedDict):
    """
    Base state for all command workflows.

    This state provides common fields needed across all workflow types including
    input tracking, workflow control, human-in-the-loop support, tool tracking,
    progress monitoring, and results.

    Fields with Annotated[List, operator.add] will accumulate values across nodes
    rather than replacing them.
    """

    # Input (Required)
    args: List[str]
    user_id: str
    session_id: str

    # Input (Optional)
    repo_id: NotRequired[str]

    # Workflow control (Required)
    workflow_id: str
    thread_id: str

    # Workflow control (Optional)
    error: NotRequired[str]
    error_type: NotRequired[str]

    # Human-in-the-loop (Required)
    awaiting_user_input: bool

    # Human-in-the-loop (Optional)
    user_input_type: NotRequired[str]
    user_prompt: NotRequired[str]
    user_response: NotRequired[str]

    # Tool access - accumulate across nodes using operator.add reducer
    tool_calls_made: Annotated[List[dict], operator.add]
    tool_results: Annotated[List[dict], operator.add]

    # Progress tracking (Required)
    progress_step: int
    progress_total: int

    # Results (Required)
    success: bool

    # Results (Optional)
    final_output: NotRequired[Any]
