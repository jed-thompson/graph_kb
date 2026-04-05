"""List files tool for the chat agent.

This module provides the list_files tool that returns
all file paths in an indexed repository.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis import (
    RepositoryNotFoundError,
    RepositoryNotReadyError,
)
from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


@dataclass
class ListFilesResult:
    """Result from a list_files tool invocation."""

    success: bool
    files: Optional[List[str]] = None
    tree: Optional[str] = None
    error: Optional[str] = None


class ListFilesTool:
    """Tool for listing all files in a repository.

    This tool uses the GraphQueryService to retrieve all indexed
    file paths and can format them as a tree structure.
    """

    # Tool schema for LLM function calling
    SCHEMA = {
        "name": "list_files",
        "description": "List all files in an indexed repository, optionally filtered by path prefix.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "path_prefix": {
                    "type": "string",
                    "description": "Optional path prefix to filter files (e.g., 'src/' or 'tests/').",
                },
                "depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to show (default: unlimited).",
                },
            },
            "required": ["repo_id"],
        },
    }

    def __init__(self, query_service: CodeQueryService):
        """Initialize the ListFilesTool.

        Args:
            query_service: The CodeQueryService for graph queries.
        """
        self._query_service = query_service

    def invoke(
        self,
        repo_id: str,
        path_prefix: Optional[str] = None,
        depth: Optional[int] = None,
    ) -> ListFilesResult:
        """Invoke the list_files tool.

        Args:
            repo_id: The repository ID.
            path_prefix: Optional path prefix to filter files.
            depth: Maximum directory depth to show.

        Returns:
            ListFilesResult containing file list and tree or error.
        """
        # Validate repository
        try:
            self._query_service.validate_repository(repo_id)
        except RepositoryNotFoundError as e:
            return ListFilesResult(success=False, error=str(e))
        except RepositoryNotReadyError as e:
            return ListFilesResult(success=False, error=str(e))

        try:
            # Get all files using query service
            files = self._query_service.list_files(repo_id)

            # Filter by prefix if provided
            if path_prefix:
                prefix = path_prefix.rstrip("/")
                files = [f for f in files if f.startswith(prefix)]

            # Filter by depth if provided
            if depth is not None:
                files = [f for f in files if f.count("/") < depth]

            # Build tree representation
            tree = self._build_tree(files)

            return ListFilesResult(
                success=True,
                files=files,
                tree=tree,
            )

        except Exception as e:
            logger.error(
                f"Failed to list files for repo {repo_id}: {e}",
                exc_info=True,
            )
            return ListFilesResult(
                success=False,
                error=f"Failed to list files: {str(e)}",
            )

    def _build_tree(self, files: List[str]) -> str:
        """Build a tree representation of file paths.

        Args:
            files: List of file paths.

        Returns:
            Tree-formatted string.
        """
        if not files:
            return "(empty)"

        # Build directory structure
        tree_dict: Dict[str, Any] = {}
        for file_path in files:
            parts = file_path.split("/")
            current = tree_dict
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            # Mark file with None
            current[parts[-1]] = None

        # Render tree
        lines = []
        self._render_tree(tree_dict, lines, "")
        return "\n".join(lines)

    def _render_tree(
        self,
        tree: Dict[str, Any],
        lines: List[str],
        prefix: str,
    ) -> None:
        """Recursively render tree structure.

        Args:
            tree: Dictionary representing directory structure.
            lines: List to append lines to.
            prefix: Current line prefix for indentation.
        """
        items = sorted(tree.items(), key=lambda x: (x[1] is not None, x[0]))
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "

            if subtree is None:
                # It's a file
                lines.append(f"{prefix}{connector}{name}")
            else:
                # It's a directory
                lines.append(f"{prefix}{connector}{name}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                self._render_tree(subtree, lines, new_prefix)

    def format_for_display(self, result: ListFilesResult) -> str:
        """Format list files result for display to user.

        Args:
            result: The list files result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Failed to list files: {result.error}"

        if not result.files:
            return "ℹ️ No files found in this repository."

        output = f"**Repository Structure** ({len(result.files)} files)\n\n"
        output += f"```\n{result.tree}\n```"
        return output
