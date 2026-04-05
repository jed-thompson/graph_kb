"""Get file snippet tool for the chat agent.

This module provides the get_file_snippet tool that retrieves exact
lines from files in indexed repositories.
"""

import os
from dataclasses import dataclass
from typing import Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis import (
    RepositoryNotFoundError,
)
from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


class FileNotFoundError(Exception):
    """Raised when a file is not found in the repository."""

    pass


class InvalidLineRangeError(Exception):
    """Raised when the line range is invalid."""

    pass


@dataclass
class SnippetResult:
    """Result from a get_file_snippet tool invocation."""

    success: bool
    content: Optional[str] = None
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    total_lines: Optional[int] = None
    error: Optional[str] = None


class GetFileSnippetTool:
    """Tool for retrieving exact file snippets from indexed repositories.

    This tool uses the GraphQueryService to get repository information
    and reads file content from local repo storage.
    """

    # Tool schema for LLM function calling
    SCHEMA = {
        "name": "get_file_snippet",
        "description": "Get the exact content of specific lines from a file in an indexed repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "file_path": {
                    "type": "string",
                    "description": "The path to the file within the repository.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "The starting line number (1-indexed).",
                },
                "end_line": {
                    "type": "integer",
                    "description": "The ending line number (1-indexed, inclusive).",
                },
            },
            "required": ["repo_id", "file_path", "start_line", "end_line"],
        },
    }

    def __init__(self, query_service: CodeQueryService):
        """Initialize the GetFileSnippetTool.

        Args:
            query_service: The CodeQueryService for repository queries.
        """
        self._query_service = query_service

    def invoke(
        self,
        repo_id: str,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> SnippetResult:
        """Invoke the get_file_snippet tool.

        Args:
            repo_id: The repository ID.
            file_path: The path to the file within the repository.
            start_line: The starting line number (1-indexed).
            end_line: The ending line number (1-indexed, inclusive).

        Returns:
            SnippetResult containing the file content or error.
        """
        # Validate line range
        validation_error = self._validate_line_range(start_line, end_line)
        if validation_error:
            return SnippetResult(success=False, error=validation_error)

        # Get repository local path via query service
        local_path = self._get_repo_local_path(repo_id)
        if local_path is None:
            return SnippetResult(
                success=False,
                error=f"Repository '{repo_id}' is not indexed.",
            )

        # Build full file path
        full_path = self._build_file_path(local_path, file_path)

        # Read file content
        try:
            content, total_lines = self._read_lines(full_path, start_line, end_line)
            return SnippetResult(
                success=True,
                content=content,
                file_path=file_path,
                start_line=start_line,
                end_line=min(end_line, total_lines),
                total_lines=total_lines,
            )
        except FileNotFoundError as e:
            return SnippetResult(success=False, error=str(e))
        except InvalidLineRangeError as e:
            return SnippetResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}", exc_info=True)
            return SnippetResult(
                success=False,
                error=f"Failed to read file: {str(e)}",
            )

    def _validate_line_range(
        self, start_line: int, end_line: int
    ) -> Optional[str]:
        """Validate the line range parameters.

        Args:
            start_line: The starting line number.
            end_line: The ending line number.

        Returns:
            Error message if validation fails, None otherwise.
        """
        if start_line < 1:
            return "start_line must be at least 1 (lines are 1-indexed)."

        if end_line < 1:
            return "end_line must be at least 1 (lines are 1-indexed)."

        if start_line > end_line:
            return f"start_line ({start_line}) cannot be greater than end_line ({end_line})."

        return None

    def _get_repo_local_path(self, repo_id: str) -> Optional[str]:
        """Get repository local path via query service.

        Args:
            repo_id: The repository ID.

        Returns:
            Local path if found, None otherwise.
        """
        try:
            return self._query_service.get_repo_local_path(repo_id)
        except RepositoryNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to get repo {repo_id}: {e}")
            return None

    def _build_file_path(self, repo_local_path: str, file_path: str) -> str:
        """Build the full file path.

        Args:
            repo_local_path: The local path to the repository.
            file_path: The relative file path within the repository.

        Returns:
            The full file path.
        """
        # Normalize the file path to prevent directory traversal
        normalized_file_path = os.path.normpath(file_path)
        if normalized_file_path.startswith(".."):
            raise ValueError("Invalid file path: directory traversal not allowed")

        return os.path.join(repo_local_path, normalized_file_path)

    def _read_lines(
        self, full_path: str, start_line: int, end_line: int
    ) -> tuple[str, int]:
        """Read specific lines from a file.

        Args:
            full_path: The full path to the file.
            start_line: The starting line number (1-indexed).
            end_line: The ending line number (1-indexed, inclusive).

        Returns:
            Tuple of (content string, total line count).

        Raises:
            FileNotFoundError: If the file doesn't exist.
            InvalidLineRangeError: If the line range is invalid for the file.
        """
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"Path is not a file: {full_path}")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            # Try with latin-1 encoding as fallback
            with open(full_path, "r", encoding="latin-1") as f:
                lines = f.readlines()

        total_lines = len(lines)

        if start_line > total_lines:
            raise InvalidLineRangeError(
                f"start_line ({start_line}) exceeds file length ({total_lines} lines)."
            )

        # Adjust end_line if it exceeds file length
        actual_end_line = min(end_line, total_lines)

        # Extract the requested lines (convert to 0-indexed)
        selected_lines = lines[start_line - 1 : actual_end_line]
        content = "".join(selected_lines)

        return content, total_lines

    def format_for_display(self, result: SnippetResult) -> str:
        """Format snippet result for display to user.

        Args:
            result: The snippet result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Failed to get file snippet: {result.error}"

        header = (
            f"**{result.file_path}** "
            f"(lines {result.start_line}-{result.end_line} of {result.total_lines})"
        )

        return f"{header}\n```\n{result.content}```"
