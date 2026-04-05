"""Data Flow Tracer V2 for tracing data flow using neo4j-graphrag.

This module provides the DataFlowTracerV2 class that traces data flow
from entry points through the call chain using CALLS relationships,
leveraging the GraphRetrieverAdapter for graph queries.
"""

import json
from typing import Any, Dict, List, Optional, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...adapters.storage.graph_retriever import GraphRetrieverAdapter
from ...models.analysis import DataFlow, DataFlowStep, EntryPoint
from ...models.analysis_enums import StepType

logger = EnhancedLogger(__name__)


# Patterns for classifying step types
PERSIST_PATTERNS = [
    "save", "store", "persist", "write", "insert", "update", "delete",
    "create", "put", "commit", "flush", "add", "remove", "set",
    "repository", "dao", "db", "database", "cache", "redis", "mongo",
]

RETURN_PATTERNS = [
    "return", "response", "result", "output", "serialize", "format",
    "render", "json", "to_dict", "to_json", "encode", "transform",
]


class DataFlowTracerV2:
    """Tracer for data flow through a codebase using neo4j-graphrag.

    Traces data flow from entry points using CALLS relationships in the graph.
    Implements depth limiting, cycle detection, and step type classification.
    """

    def __init__(self, retriever: GraphRetrieverAdapter):
        """Initialize the DataFlowTracerV2.

        Args:
            retriever: The GraphRetrieverAdapter for graph queries.
        """
        self._retriever = retriever

    def trace(
        self,
        entry_point: EntryPoint,
        max_depth: int = 10,
    ) -> DataFlow:
        """Trace data flow from an entry point.

        Args:
            entry_point: The entry point to trace from.
            max_depth: Maximum depth to trace (default 10).

        Returns:
            DataFlow containing the traced steps.
        """
        if max_depth < 1:
            max_depth = 1

        steps: List[DataFlowStep] = []
        visited: Set[str] = set()

        # Add the entry point as the first step
        entry_step = self._create_step_from_entry_point(entry_point)
        steps.append(entry_step)
        visited.add(entry_point.id)

        # Trace the call chain using the retriever
        paths = self._retriever.traverse_calls(entry_point.id, max_depth)

        # Process the paths to extract steps
        is_truncated, max_depth_reached = self._process_paths(
            paths, steps, visited, max_depth
        )

        return DataFlow(
            entry_point=entry_point,
            steps=steps,
            is_truncated=is_truncated,
            max_depth_reached=max_depth_reached,
        )

    def _process_paths(
        self,
        paths: List[Dict[str, Any]],
        steps: List[DataFlowStep],
        visited: Set[str],
        max_depth: int,
    ) -> tuple[bool, int]:
        """Process traversal paths to extract steps.

        Args:
            paths: List of path dictionaries from traverse_calls.
            steps: List to append steps to.
            visited: Set of visited symbol IDs.
            max_depth: Maximum depth to trace.

        Returns:
            Tuple of (is_truncated, max_depth_reached).
        """
        max_depth_reached = 0
        is_truncated = False

        for path in paths:
            nodes = path.get("nodes", [])

            # Skip the first node (entry point) and process the rest
            for i, node in enumerate(nodes[1:], start=1):
                node_id = node.get("id")
                if not node_id or node_id in visited:
                    continue

                # Check if we've reached max depth
                if i > max_depth:
                    is_truncated = True
                    break

                visited.add(node_id)

                # Parse attributes
                attrs = self._parse_attrs(node.get("attrs", "{}"))

                # Create step
                step = self._create_step_from_attrs(node_id, attrs, depth=i)
                steps.append(step)

                if i > max_depth_reached:
                    max_depth_reached = i

        # If we reached the max_depth, mark as truncated since there could be more nodes beyond
        if max_depth_reached >= max_depth:
            is_truncated = True

        return is_truncated, max_depth_reached

    def _parse_attrs(self, attrs: Any) -> Dict[str, Any]:
        """Parse symbol attributes from string or dict.

        Args:
            attrs: The attributes as string or dict.

        Returns:
            Parsed attributes dictionary.
        """
        if isinstance(attrs, str):
            try:
                return json.loads(attrs)
            except json.JSONDecodeError:
                return {}
        elif isinstance(attrs, dict):
            return attrs
        return {}

    def _create_step_from_entry_point(self, entry_point: EntryPoint) -> DataFlowStep:
        """Create a DataFlowStep from an EntryPoint.

        Args:
            entry_point: The entry point.

        Returns:
            A DataFlowStep representing the entry point.
        """
        return DataFlowStep(
            symbol_id=entry_point.id,
            symbol_name=entry_point.name,
            file_path=entry_point.file_path,
            step_type=StepType.ENTRY,
            depth=0,
            docstring=entry_point.description,
        )

    def _create_step_from_attrs(
        self,
        symbol_id: str,
        attrs: Dict[str, Any],
        depth: int,
    ) -> DataFlowStep:
        """Create a DataFlowStep from symbol attributes.

        Args:
            symbol_id: The symbol ID.
            attrs: The symbol attributes.
            depth: The depth in the trace.

        Returns:
            A DataFlowStep representing the symbol.
        """
        name = attrs.get("name", symbol_id.split(":")[-1])
        file_path = attrs.get("file_path", "")
        docstring = attrs.get("docstring")

        step_type = self._classify_step_type(name, file_path, docstring)

        return DataFlowStep(
            symbol_id=symbol_id,
            symbol_name=name,
            file_path=file_path,
            step_type=step_type,
            depth=depth,
            docstring=docstring,
        )

    def _classify_step_type(
        self,
        name: str,
        file_path: str,
        docstring: Optional[str],
    ) -> StepType:
        """Classify the step type based on name, file path, and docstring.

        Args:
            name: The symbol name.
            file_path: The file path.
            docstring: The docstring (if any).

        Returns:
            The classified StepType.
        """
        name_lower = name.lower()
        file_lower = file_path.lower() if file_path else ""
        doc_lower = docstring.lower() if docstring else ""

        # Check for persist patterns
        for pattern in PERSIST_PATTERNS:
            if pattern in name_lower or pattern in file_lower or pattern in doc_lower:
                return StepType.PERSIST

        # Check for return patterns
        for pattern in RETURN_PATTERNS:
            if pattern in name_lower or pattern in doc_lower:
                return StepType.RETURN

        # Default to process
        return StepType.PROCESS
