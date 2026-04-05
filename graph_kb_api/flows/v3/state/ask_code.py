"""
AskCode state schema for agentic code question answering workflow.

This module defines the state structure for the AskCode workflow which supports
iterative tool calling, clarification loops, and conversation history.
"""

from __future__ import annotations

import operator
from typing import Annotated, List, Literal

from typing_extensions import NotRequired, TypedDict

from langgraph.graph import add_messages

from graph_kb_api.flows.v3.state.common import BaseCommandState
from graph_kb_api.graph_kb.querying.models import GraphRAGResult


class AskCodeState(BaseCommandState, TypedDict):
    """
    State for AskCode agentic workflow.

    This state extends BaseCommandState with fields specific to code question
    answering including question clarity tracking, LLM message history with
    add_messages reducer, context retrieval tracking, agentic tool loop control,
    and conversation history.

    The messages field uses add_messages reducer which intelligently merges
    message lists, handling tool calls and responses properly.
    """

    # Input
    original_question: NotRequired[str]
    refined_question: NotRequired[str]

    # UI/Progress tracking
    progress_message_id: NotRequired[str]

    # Clarification loop
    question_clarity: Literal["clear", "vague", "ambiguous"]
    clarification_attempts: int

    # Messages for LLM interactions - use add_messages reducer
    # This reducer intelligently merges message lists, handling tool calls properly
    messages: Annotated[list, add_messages]

    # Retrieval results - accumulate across nodes using operator.add
    context_items: Annotated[List[dict], operator.add]
    context_sufficiency: Literal["sufficient", "sparse", "none"]
    additional_queries_made: int

    # Graph expansion results (from GraphExpansionNode)
    graph_context: NotRequired[GraphRAGResult]  # Full graph expansion result
    total_nodes_explored: int  # Number of graph nodes traversed
    symbols_found: List[str]  # Starting symbols from vector search
    visualization: NotRequired[str]  # Mermaid diagram of discovered relationships
    graph_expansion_skipped: bool  # Whether graph expansion was skipped (service unavailable, disabled, or error)

    # Legacy flow context (kept for backward compatibility)
    flow_context: Annotated[List[dict], operator.add]

    # Performance tracking
    vector_search_duration: float  # Duration of vector search in seconds
    graph_expansion_duration: float  # Duration of graph expansion in seconds

    # Graph expansion configuration
    max_depth: int  # Maximum traversal depth for graph expansion (default: 5)
    max_expansion_nodes: int  # Maximum nodes to explore during expansion (default: 500)
    enable_graph_expansion: bool  # Whether graph expansion is enabled (default: True)

    # Agentic tool loop
    agent_iterations: int
    max_agent_iterations: int  # Default: 5
    agent_needs_more_info: bool
    tool_calls_history: Annotated[List[dict], operator.add]  # Track all tool calls made

    # Response
    llm_response: NotRequired[str]
    final_output: NotRequired[str]  # Final formatted output for presentation
    agent_reasoning: NotRequired[str]

    # User feedback loop
    user_satisfied: NotRequired[bool]
    follow_up_question: NotRequired[str]
    conversation_history: Annotated[List[dict], operator.add]

    # Visualization
    mermaid_code: NotRequired[str]
