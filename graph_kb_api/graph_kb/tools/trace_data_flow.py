"""Trace data flow tool for the chat agent.

This module provides the trace_data_flow tool that traces
data flow from an entry point through the call chain.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.analysis import EntryPoint
from ..models.analysis_enums import EntryPointType
from ..services.analysis_service import CodeAnalysisService

logger = EnhancedLogger(__name__)


@dataclass
class TraceDataFlowResult:
    """Result from a trace_data_flow tool invocation."""

    success: bool
    entry_point: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    is_truncated: bool = False
    max_depth_reached: int = 0
    error: Optional[str] = None


class TraceDataFlowTool:
    """Tool for tracing data flow from entry points.

    This tool traces how data flows through the codebase starting
    from an entry point (HTTP endpoint, CLI command, etc.) through
    the call chain.
    """

    SCHEMA = {
        "name": "trace_data_flow",
        "description": "Trace data flow from a function or entry point through its call chain to understand how data is processed.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "symbol_name": {
                    "type": "string",
                    "description": "The name of the function or entry point to trace from.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth to trace (default: 10).",
                },
            },
            "required": ["repo_id", "symbol_name"],
        },
    }

    def __init__(
        self,
        analysis_service: CodeAnalysisService,
    ):
        """Initialize the TraceDataFlowTool.

        Args:
            analysis_service: The CodeAnalysisService for analysis operations.
        """
        self._analysis_service = analysis_service

    def invoke(
        self,
        repo_id: str,
        symbol_name: str,
        max_depth: int = 10,
    ) -> TraceDataFlowResult:
        """Invoke the trace_data_flow tool.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to trace from.
            max_depth: Maximum trace depth.

        Returns:
            TraceDataFlowResult containing the trace or error.
        """
        try:
            # Create a synthetic entry point for tracing
            # We need to get the symbol ID and file path first
            # For now, we'll create a minimal entry point
            entry_point = EntryPoint(
                id=f"{repo_id}:{symbol_name}",  # Simplified ID
                name=symbol_name,
                file_path="",  # Will be resolved by the service
                entry_type=EntryPointType.MAIN_FUNCTION,  # Default type
            )

            # Trace data flow using CodeAnalysisService
            data_flow = self._analysis_service.trace_data_flow(
                entry_point=entry_point,
                max_depth=max_depth,
            )

            # Convert steps to dicts
            steps = []
            for step in data_flow.steps:
                steps.append({
                    "symbol_name": step.symbol_name,
                    "file_path": step.file_path,
                    "step_type": step.step_type.value,
                    "depth": step.depth,
                    "docstring": step.docstring[:200] if step.docstring else None,
                })

            return TraceDataFlowResult(
                success=True,
                entry_point=symbol_name,
                steps=steps,
                is_truncated=data_flow.is_truncated,
                max_depth_reached=data_flow.max_depth_reached,
            )

        except Exception as e:
            logger.error(f"Failed to trace data flow: {e}", exc_info=True)
            return TraceDataFlowResult(
                success=False,
                error=f"Failed to trace data flow: {str(e)}",
            )

    def format_for_display(self, result: TraceDataFlowResult) -> str:
        """Format result for display."""
        if not result.success:
            return f"❌ {result.error}"

        if not result.steps:
            return f"ℹ️ No data flow found from `{result.entry_point}`"

        output = [f"**Data flow from `{result.entry_point}`** ({len(result.steps)} steps):\n"]

        for step in result.steps:
            depth_indent = "  " * step["depth"]
            step_icon = {
                "ENTRY": "🚀",
                "PROCESS": "⚙️",
                "PERSIST": "💾",
                "RETURN": "↩️",
            }.get(step["step_type"], "•")

            line = f"{depth_indent}{step_icon} `{step['symbol_name']}`"
            if step["file_path"]:
                line += f" in `{step['file_path']}`"
            output.append(line)

        if result.is_truncated:
            output.append(f"\n*Trace truncated at depth {result.max_depth_reached}*")

        return "\n".join(output)
