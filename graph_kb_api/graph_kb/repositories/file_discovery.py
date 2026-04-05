"""File discovery and filtering for repository ingestion.

This module handles discovering files in a repository and filtering them
based on extension, size, gitignore patterns, and custom exclude patterns.
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Set

import pathspec

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.base import IngestionConfig

logger = EnhancedLogger(__name__)


class FileDiscovery(ABC):
    """Abstract base class for file discovery and filtering.

    This interface defines the contract for discovering and filtering files
    for ingestion based on various criteria.
    """

    @abstractmethod
    def should_include_file(
        self,
        file_path: str,
        file_size_bytes: Optional[int] = None,
        gitignore_spec: Optional[pathspec.PathSpec] = None,
        exclude_spec: Optional[pathspec.PathSpec] = None,
    ) -> bool:
        """Check if a file should be included for indexing.

        Args:
            file_path: Relative path to the file from repo root.
            file_size_bytes: File size in bytes (optional).
            gitignore_spec: PathSpec for gitignore patterns.
            exclude_spec: PathSpec for extra exclude patterns.

        Returns:
            True if the file should be included.
        """
        pass

    @abstractmethod
    def discover_files(self, repo_path: str) -> List[str]:
        """Discover all files eligible for indexing.

        Args:
            repo_path: Path to the repository root.

        Returns:
            List of relative file paths eligible for indexing.
        """
        pass

    @abstractmethod
    def get_file_language(self, file_path: str) -> str:
        """Get the language for a file based on extension.

        Args:
            file_path: Path to the file.

        Returns:
            Language identifier string.
        """
        pass


class FileSystemDiscovery(FileDiscovery):
    """Discovers and filters files for ingestion.

    This class provides functionality to:
    - Discover all files in a repository
    - Filter files based on extension whitelist
    - Filter files based on size limits
    - Respect .gitignore patterns
    - Apply custom exclude patterns
    """
    """Discovers and filters files for ingestion.

    This class provides functionality to:
    - Discover all files in a repository
    - Filter files based on extension whitelist
    - Filter files based on size limits
    - Respect .gitignore patterns
    - Apply custom exclude patterns
    """

    def __init__(self, config: Optional[IngestionConfig] = None):
        """Initialize FileDiscovery.

        Args:
            config: Ingestion configuration with filtering rules.
        """
        self.config = config or IngestionConfig()
        self._include_extensions: Set[str] = set(self.config.include_extensions)

    def _load_gitignore(self, repo_path: Path) -> Optional[pathspec.PathSpec]:
        """Load and process .gitignore file.

        Args:
            repo_path: Path to the repository root.

        Returns:
            PathSpec object for matching, or None if no .gitignore exists.
        """
        gitignore_path = repo_path / ".gitignore"
        if not gitignore_path.exists():
            return None

        try:
            with open(gitignore_path, "r", encoding="utf-8") as f:
                patterns = f.read().splitlines()
            return pathspec.PathSpec.from_lines("gitignore", patterns)
        except Exception as e:
            logger.warning(f"Failed to process .gitignore: {e}")
            return None

    def _create_exclude_spec(self) -> pathspec.PathSpec:
        """Create PathSpec for extra exclude patterns.

        Returns:
            PathSpec object for matching exclude patterns.
        """
        return pathspec.PathSpec.from_lines(
            "gitignore", self.config.extra_exclude_patterns
        )

    def _has_valid_extension(self, file_path: str) -> bool:
        """Check if file has a valid extension.

        Args:
            file_path: Path to the file.

        Returns:
            True if extension is in the include list.
        """
        ext = Path(file_path).suffix.lower()
        return ext in self._include_extensions

    def _is_within_size_limit(self, file_path: Path) -> bool:
        """Check if file is within size limit.

        Args:
            file_path: Path to the file.

        Returns:
            True if file size is within limit.
        """
        try:
            size_kb = file_path.stat().st_size / 1024
            return size_kb <= self.config.max_file_size_kb
        except OSError:
            return False

    def should_include_file(
        self,
        file_path: str,
        file_size_bytes: Optional[int] = None,
        gitignore_spec: Optional[pathspec.PathSpec] = None,
        exclude_spec: Optional[pathspec.PathSpec] = None,
    ) -> bool:
        """Check if a file should be included for indexing.

        Args:
            file_path: Relative path to the file from repo root.
            file_size_bytes: File size in bytes (optional, will be checked if provided).
            gitignore_spec: PathSpec for gitignore patterns.
            exclude_spec: PathSpec for extra exclude patterns.

        Returns:
            True if the file should be included.
        """
        # Check extension
        if not self._has_valid_extension(file_path):
            return False

        # Check size if provided
        if file_size_bytes is not None:
            size_kb = file_size_bytes / 1024
            if size_kb > self.config.max_file_size_kb:
                return False

        # Check gitignore patterns
        if gitignore_spec is not None and gitignore_spec.match_file(file_path):
            return False

        # Check extra exclude patterns
        if exclude_spec is None:
            exclude_spec = self._create_exclude_spec()
        if exclude_spec.match_file(file_path):
            return False

        return True

    def discover_files(self, repo_path: str) -> List[str]:
        """Discover all files eligible for indexing.

        Args:
            repo_path: Path to the repository root.

        Returns:
            List of relative file paths eligible for indexing.
        """
        repo_path = Path(repo_path)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            return []

        # Load gitignore
        gitignore_spec = self._load_gitignore(repo_path)

        # Create exclude spec
        exclude_spec = self._create_exclude_spec()

        eligible_files: List[str] = []

        # Walk the repository
        for root, dirs, files in os.walk(repo_path):
            root_path = Path(root)

            # Skip .git directory
            if ".git" in dirs:
                dirs.remove(".git")

            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for file_name in files:
                # Skip hidden files
                if file_name.startswith("."):
                    continue

                file_path = root_path / file_name
                relative_path = str(file_path.relative_to(repo_path))

                # Get file size
                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    continue

                # Check if file should be included
                if self.should_include_file(
                    relative_path,
                    file_size_bytes=file_size,
                    gitignore_spec=gitignore_spec,
                    exclude_spec=exclude_spec,
                ):
                    eligible_files.append(relative_path)

        logger.info(f"Discovered {len(eligible_files)} eligible files in {repo_path}")
        return sorted(eligible_files)

    def get_file_language(self, file_path: str) -> str:
        """Get the language for a file based on extension.

        Args:
            file_path: Path to the file.

        Returns:
            Language identifier string.
        """
        ext = Path(file_path).suffix.lower()
        extension_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
            ".java": "java",
            ".rb": "ruby",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
            ".cs": "csharp",
            ".md": "markdown",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
        }
        return extension_map.get(ext, "unknown")
