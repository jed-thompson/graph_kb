"""
Progress display utilities for code analysis workflows.

This module provides centralized utilities for displaying progress messages
during code analysis operations, ensuring consistent messaging across all nodes.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ProgressStep:
    """Represents a single step in the progress display."""
    number: int
    total: int
    name: str
    status: str  # "complete", "active", "pending"
    details: Optional[str] = None


class CodeAnalysisProgressDisplay:
    """Manages progress display for code analysis workflows."""

    # Step definitions (8-step granular model)
    STEP_QUESTION_ANALYZED = "Question analyzed"
    STEP_EMBEDDING_GENERATION = "Generating embeddings"
    STEP_VECTOR_SEARCH = "Vector similarity search"
    STEP_GRAPH_EXPANSION = "Graph expansion"
    STEP_CONTEXT_RANKING = "Ranking & pruning context"
    STEP_AGENT_ANALYZING = "Agent analyzing context"
    STEP_FORMATTING_RESPONSE = "Formatting response"
    STEP_COMPLETE = "Complete"

    # Legacy step names (for backward compatibility)
    STEP_SEMANTIC_SEARCH = "Semantic search"
    STEP_BUILDING_CONTEXT = "Building context"
    STEP_GENERATING_RESPONSE = "Generating response"
    STEP_GATHERING_CONTEXT = "Gathering additional context"
    STEP_PRESENTING = "Presenting to user"

    TOTAL_STEPS = 8  # Changed from 5 to 8 for more granular progress

    @staticmethod
    def step_0_starting(repo_id: str) -> str:
        """Display: Initial message when starting analysis."""
        steps = [
            ProgressStep(1, 8, "Analyzing question", "active"),
            ProgressStep(2, 8, CodeAnalysisProgressDisplay.STEP_EMBEDDING_GENERATION, "pending"),
            ProgressStep(3, 8, CodeAnalysisProgressDisplay.STEP_VECTOR_SEARCH, "pending"),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "pending"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]

        additional = "⏱️ *This may take 30-60 seconds for large repositories...*"
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, additional)

    @staticmethod
    def _format_step(step: ProgressStep) -> str:
        """Format a single progress step."""
        if step.status == "complete":
            icon = "✅"
            text = step.name
            if step.details:
                text = f"{step.name} - {step.details}"
        elif step.status == "active":
            icon = "⏳"
            text = step.name
            if step.details:
                text = f"{step.name} - {step.details}"
        else:  # pending
            icon = "⬜"
            text = step.name

        return f"{icon} Step {step.number}/{step.total}: {text}"

    @staticmethod
    def format_progress(
        repo_id: str,
        steps: List[ProgressStep],
        additional_info: Optional[str] = None
    ) -> str:
        """
        Format a complete progress display message.

        Args:
            repo_id: Repository identifier
            steps: List of progress steps to display
            additional_info: Optional additional information to append

        Returns:
            Formatted progress message
        """
        lines = [f"🔍 **Code Analysis:** `{repo_id}`"]
        lines.append("")  # Empty line for spacing

        for step in steps:
            lines.append(CodeAnalysisProgressDisplay._format_step(step))

        if additional_info:
            lines.append(f"\n{additional_info}")

        return "\n".join(lines)

    @staticmethod
    def step_1_question_analyzed(repo_id: str) -> str:
        """Display: Question analyzed, starting embedding generation."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, CodeAnalysisProgressDisplay.STEP_EMBEDDING_GENERATION, "active"),
            ProgressStep(3, 8, CodeAnalysisProgressDisplay.STEP_VECTOR_SEARCH, "pending"),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "pending"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_2_embedding_generation(repo_id: str, loading_model: bool = False) -> str:
        """Display: Generating query embeddings."""
        details = "Loading embedding model..." if loading_model else None
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, CodeAnalysisProgressDisplay.STEP_EMBEDDING_GENERATION, "active", details),
            ProgressStep(3, 8, CodeAnalysisProgressDisplay.STEP_VECTOR_SEARCH, "pending"),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "pending"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_3_vector_search(repo_id: str, candidates_found: int = 0) -> str:
        """Display: Performing vector similarity search."""
        details = f"Found {candidates_found} initial candidates" if candidates_found > 0 else None
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, CodeAnalysisProgressDisplay.STEP_VECTOR_SEARCH, "active", details),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "pending"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_4_graph_expansion(repo_id: str, expanding: bool = True, nodes_explored: int = 0) -> str:
        """Display: Expanding context via graph relationships."""
        if nodes_explored > 0:
            details = f"Explored {nodes_explored} graph nodes"
        elif expanding:
            details = "Expanding via relationships..."
        else:
            details = None

        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "active", details),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_5_context_ranking(repo_id: str, num_candidates: int = 0) -> str:
        """Display: Ranking and pruning context."""
        details = f"Ranking {num_candidates} candidates" if num_candidates > 0 else None
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "active", details),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_6_agent_analyzing(repo_id: str, num_chunks: int = 0) -> str:
        """Display: Agent analyzing retrieved context."""
        details = f"Analyzing {num_chunks} code chunks" if num_chunks > 0 else None
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "active", details),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_2_semantic_search_timeout(repo_id: str, elapsed: int) -> str:
        """Display: Embedding generation taking longer than expected."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, CodeAnalysisProgressDisplay.STEP_EMBEDDING_GENERATION, "active"),
            ProgressStep(3, 8, CodeAnalysisProgressDisplay.STEP_VECTOR_SEARCH, "pending"),
            ProgressStep(4, 8, CodeAnalysisProgressDisplay.STEP_GRAPH_EXPANSION, "pending"),
            ProgressStep(5, 8, CodeAnalysisProgressDisplay.STEP_CONTEXT_RANKING, "pending"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_AGENT_ANALYZING, "pending"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]
        additional = f"⏱️ *Still processing... ({elapsed}s since last update)*"
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, additional)

    @staticmethod
    def step_3_graph_expansion(repo_id: str, num_chunks: int) -> str:
        """Display: Context retrieval complete, agent analyzing (LEGACY - redirects to step_6)."""
        # This is now step 6 in the new 8-step model
        return CodeAnalysisProgressDisplay.step_6_agent_analyzing(repo_id, num_chunks)

    @staticmethod
    def step_3_agent_analyzing(repo_id: str) -> str:
        """Display: Agent analyzing context (LEGACY - redirects to step_6)."""
        return CodeAnalysisProgressDisplay.step_6_agent_analyzing(repo_id)

    @staticmethod
    def step_3_gathering_context(
        repo_id: str,
        tool_descriptions: List[str],
        tools_summary: str
    ) -> str:
        """Display: Gathering additional context with tool calls (agent step 6)."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_GATHERING_CONTEXT, "active"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]

        tool_info = (
            f"---\n\n"
            f"**🔧 Tool Calls ({tools_summary}):**\n\n"
            f"{chr(10).join(tool_descriptions)}"
        )

        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, tool_info)

    @staticmethod
    def step_3_tool_execution_keepalive(
        repo_id: str,
        tool_name: str,
        tool_desc: str,
        current_tool: int,
        total_tools: int,
        elapsed: int
    ) -> str:
        """Display: Tool execution keepalive message during long-running operations."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, CodeAnalysisProgressDisplay.STEP_GATHERING_CONTEXT, "active",
                        f"Executing tool {current_tool}/{total_tools}"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "pending"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]

        tool_info = (
            f"---\n\n"
            f"**🔧 Current Tool:** {tool_desc}\n\n"
            f"⏱️ *Tool running for {elapsed}s... (this may take up to 90s for complex searches)*"
        )

        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, tool_info)

    @staticmethod
    def step_4_analyzing_results(
        repo_id: str,
        completed_calls: List[Dict[str, Any]],
        tool_display: str
    ) -> str:
        """Display: Analyzing tool results (step 6 continuation)."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, "Additional context gathered", "complete"),
            ProgressStep(7, 8, "Analyzing results", "active"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_COMPLETE, "pending"),
        ]

        tool_info = (
            f"---\n\n"
            f"**🔧 Tool Calls ({len(completed_calls)} completed):**\n\n"
            f"{tool_display}"
        )

        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, tool_info)

    @staticmethod
    def step_4_building_final_response(repo_id: str, tool_summary: str = "") -> str:
        """Display: Building final response after tool execution (step 7)."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, "Agent analysis complete", "complete"),
            ProgressStep(7, 8, "Building final response", "active"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_PRESENTING, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, tool_summary)

    @staticmethod
    def step_4_formatting_response(repo_id: str) -> str:
        """Display: Formatting response (step 7)."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, "Agent analysis complete", "complete"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "active"),
            ProgressStep(8, 8, CodeAnalysisProgressDisplay.STEP_PRESENTING, "pending"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps)

    @staticmethod
    def step_5_complete(repo_id: str, tool_summary: str = "") -> str:
        """Display: All steps complete (step 8)."""
        steps = [
            ProgressStep(1, 8, CodeAnalysisProgressDisplay.STEP_QUESTION_ANALYZED, "complete"),
            ProgressStep(2, 8, "Embeddings generated", "complete"),
            ProgressStep(3, 8, "Vector search complete", "complete"),
            ProgressStep(4, 8, "Graph expansion complete", "complete"),
            ProgressStep(5, 8, "Context ranked", "complete"),
            ProgressStep(6, 8, "Agent analysis complete", "complete"),
            ProgressStep(7, 8, CodeAnalysisProgressDisplay.STEP_FORMATTING_RESPONSE, "complete"),
            ProgressStep(8, 8, "Complete!", "complete"),
        ]
        return CodeAnalysisProgressDisplay.format_progress(repo_id, steps, tool_summary)
