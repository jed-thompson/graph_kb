"""Entry Point Analyzer V2 for discovering entry points using neo4j-graphrag.

This module provides the EntryPointAnalyzerV2 class that identifies entry points
such as HTTP endpoints, CLI commands, main functions, and event handlers,
using the GraphRetrieverAdapter for graph queries.
"""

import json
import re
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...adapters.storage.graph_retriever import GraphRetrieverAdapter
from ...models.analysis import EntryPoint
from ...models.analysis_enums import EntryPointType
from ...models.enums import SymbolKind

logger = EnhancedLogger(__name__)


# File patterns for entry point detection
HTTP_FILE_PATTERNS = [
    r"routes?\.py$",
    r"views?\.py$",
    r"api\.py$",
    r"endpoints?\.py$",
    r"handlers?\.py$",
    r"controllers?\.py$",
]

CLI_FILE_PATTERNS = [
    r"cli\.py$",
    r"__main__\.py$",
    r"main\.py$",
    r"commands?\.py$",
]

# Function name patterns for entry point detection
HTTP_NAME_PATTERNS = [
    r"^get_",
    r"^post_",
    r"^put_",
    r"^patch_",
    r"^delete_",
    r"^create_",
    r"^update_",
    r"^list_",
    r"^retrieve_",
]

CLI_NAME_PATTERNS = [
    r"^main$",
    r"^cli$",
    r"^run$",
    r"^execute$",
    r"^command_",
    r"_command$",
]

EVENT_HANDLER_PATTERNS = [
    r"^on_",
    r"^handle_",
    r"_handler$",
    r"_callback$",
    r"^process_",
    r"_listener$",
]

SCHEDULED_TASK_PATTERNS = [
    r"^task_",
    r"_task$",
    r"^job_",
    r"_job$",
    r"^schedule_",
    r"^cron_",
]


class EntryPointAnalyzerV2:
    """Analyzer for discovering entry points using neo4j-graphrag.

    Entry points are functions, methods, or endpoints that serve as external
    interfaces to the codebase (API endpoints, CLI commands, main functions,
    event handlers).

    Detection uses heuristics based on file names and function names since
    decorator information is not currently stored in the graph.
    """

    def __init__(self, retriever: GraphRetrieverAdapter):
        """Initialize the EntryPointAnalyzerV2.

        Args:
            retriever: The GraphRetrieverAdapter for graph queries.
        """
        self._retriever = retriever

    def analyze(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[EntryPoint]:
        """Analyze a repository to discover entry points.

        Args:
            repo_id: The repository ID to analyze.
            folder_path: Optional folder path to limit analysis scope.

        Returns:
            List of discovered EntryPoint objects.
        """
        # Get all function and method symbols
        symbols = self._retriever.find_entry_points(repo_id, folder_path)

        # Classify each symbol
        entry_points: List[EntryPoint] = []
        for symbol_data in symbols:
            attrs = self._parse_attrs(symbol_data.get("attrs", "{}"))

            # Apply folder filter if specified
            file_path = attrs.get("file_path", "")
            if folder_path and not file_path.startswith(folder_path):
                continue

            entry_type = self._classify_entry_point(attrs)
            if entry_type is not None:
                entry_point = self._create_entry_point(
                    symbol_data.get("id", ""),
                    attrs,
                    entry_type,
                )
                entry_points.append(entry_point)

        # Sort by entry type and then by name for consistent ordering
        entry_points.sort(key=lambda ep: (ep.entry_type.value, ep.name))

        return entry_points

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

    def _classify_entry_point(self, attrs: Dict[str, Any]) -> Optional[EntryPointType]:
        """Classify a symbol as an entry point type or None if not an entry point.

        Args:
            attrs: The symbol attributes.

        Returns:
            EntryPointType if the symbol is an entry point, None otherwise.
        """
        name = attrs.get("name", "").lower()
        file_path = attrs.get("file_path", "").lower()

        # Check for main function first (highest priority)
        if self._is_main_function(name, file_path):
            return EntryPointType.MAIN_FUNCTION

        # Check for HTTP endpoints
        if self._is_http_endpoint(name, file_path):
            return EntryPointType.HTTP_ENDPOINT

        # Check for CLI commands
        if self._is_cli_command(name, file_path):
            return EntryPointType.CLI_COMMAND

        # Check for event handlers
        if self._is_event_handler(name):
            return EntryPointType.EVENT_HANDLER

        # Check for scheduled tasks
        if self._is_scheduled_task(name):
            return EntryPointType.SCHEDULED_TASK

        return None

    def _is_main_function(self, name: str, file_path: str) -> bool:
        """Check if a symbol is a main function entry point.

        Args:
            name: The symbol name (lowercase).
            file_path: The file path (lowercase).

        Returns:
            True if this is a main function entry point.
        """
        # Direct main function
        if name == "main":
            return True

        # __main__.py with specific function names
        if "__main__.py" in file_path and name in ("main", "run", "cli", "execute"):
            return True

        return False

    def _is_http_endpoint(self, name: str, file_path: str) -> bool:
        """Check if a symbol is an HTTP endpoint.

        Args:
            name: The symbol name (lowercase).
            file_path: The file path (lowercase).

        Returns:
            True if this is likely an HTTP endpoint.
        """
        # Check file patterns
        file_matches = any(
            re.search(pattern, file_path, re.IGNORECASE)
            for pattern in HTTP_FILE_PATTERNS
        )

        # Check name patterns
        name_matches = any(
            re.search(pattern, name, re.IGNORECASE)
            for pattern in HTTP_NAME_PATTERNS
        )

        # Need both file and name match for higher confidence
        # Or just name match in API-related files
        if file_matches and name_matches:
            return True

        # Strong name patterns in any file
        strong_patterns = [r"^get_", r"^post_", r"^put_", r"^delete_"]
        if any(re.search(p, name, re.IGNORECASE) for p in strong_patterns):
            if file_matches:
                return True

        return False

    def _is_cli_command(self, name: str, file_path: str) -> bool:
        """Check if a symbol is a CLI command.

        Args:
            name: The symbol name (lowercase).
            file_path: The file path (lowercase).

        Returns:
            True if this is likely a CLI command.
        """
        # Check file patterns
        file_matches = any(
            re.search(pattern, file_path, re.IGNORECASE)
            for pattern in CLI_FILE_PATTERNS
        )

        # Check name patterns
        name_matches = any(
            re.search(pattern, name, re.IGNORECASE)
            for pattern in CLI_NAME_PATTERNS
        )

        # CLI commands typically in CLI files with command-like names
        if file_matches and name_matches:
            return True

        # Commands directory pattern
        if "/commands/" in file_path and name_matches:
            return True

        return False

    def _is_event_handler(self, name: str) -> bool:
        """Check if a symbol is an event handler.

        Args:
            name: The symbol name (lowercase).

        Returns:
            True if this is likely an event handler.
        """
        return any(
            re.search(pattern, name, re.IGNORECASE)
            for pattern in EVENT_HANDLER_PATTERNS
        )

    def _is_scheduled_task(self, name: str) -> bool:
        """Check if a symbol is a scheduled task.

        Args:
            name: The symbol name (lowercase).

        Returns:
            True if this is likely a scheduled task.
        """
        return any(
            re.search(pattern, name, re.IGNORECASE)
            for pattern in SCHEDULED_TASK_PATTERNS
        )

    def _create_entry_point(
        self,
        symbol_id: str,
        attrs: Dict[str, Any],
        entry_type: EntryPointType,
    ) -> EntryPoint:
        """Create an EntryPoint from symbol attributes and its classified type.

        Args:
            symbol_id: The symbol ID.
            attrs: The symbol attributes.
            entry_type: The classified entry point type.

        Returns:
            An EntryPoint object.
        """
        name = attrs.get("name", "")
        file_path = attrs.get("file_path", "")
        kind_str = attrs.get("kind", "function")

        # Determine symbol kind
        symbol_kind = self._parse_symbol_kind(kind_str)

        # Extract HTTP method from name if applicable
        http_method = None
        if entry_type == EntryPointType.HTTP_ENDPOINT:
            http_method = self._extract_http_method(name)

        # Extract line number from attrs or symbol ID
        line_number = attrs.get("line_number") or self._extract_line_number(symbol_id)

        return EntryPoint(
            id=symbol_id,
            name=name,
            file_path=file_path,
            entry_type=entry_type,
            symbol_kind=symbol_kind,
            line_number=line_number,
            http_method=http_method,
            route=None,  # Cannot determine without decorator info
            description=attrs.get("docstring"),
        )

    def _parse_symbol_kind(self, kind_str: str) -> SymbolKind:
        """Parse a symbol kind string to SymbolKind enum.

        Args:
            kind_str: The kind string from the symbol.

        Returns:
            The corresponding SymbolKind enum value.
        """
        kind_lower = kind_str.lower() if kind_str else "function"
        try:
            return SymbolKind(kind_lower)
        except ValueError:
            return SymbolKind.FUNCTION

    def _extract_http_method(self, name: str) -> Optional[str]:
        """Extract HTTP method from function name.

        Args:
            name: The function name.

        Returns:
            HTTP method string (GET, POST, etc.) or None.
        """
        name_lower = name.lower()
        if name_lower.startswith("get_") or name_lower.startswith("retrieve_") or name_lower.startswith("list_"):
            return "GET"
        elif name_lower.startswith("post_") or name_lower.startswith("create_"):
            return "POST"
        elif name_lower.startswith("put_") or name_lower.startswith("update_"):
            return "PUT"
        elif name_lower.startswith("patch_"):
            return "PATCH"
        elif name_lower.startswith("delete_"):
            return "DELETE"
        return None

    def _extract_line_number(self, symbol_id: str) -> Optional[int]:
        """Extract line number from symbol ID if encoded.

        Args:
            symbol_id: The symbol ID.

        Returns:
            Line number if found, None otherwise.
        """
        # Symbol IDs may contain line info like "repo:file:func:10"
        # This is a best-effort extraction
        parts = symbol_id.split(":")
        if len(parts) >= 4:
            try:
                return int(parts[-1])
            except ValueError:
                pass
        return None
