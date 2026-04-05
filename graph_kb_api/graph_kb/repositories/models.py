"""Repository-related data models.

This module contains data models specific to repository management operations,
including Git operations, file discovery, and repository metadata.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RepoInfo:
    """Repository information."""
    repo_id: str
    url: str
    path: str
    branch: str
    commit_sha: str
    last_updated: datetime


@dataclass
class CloneResult:
    """Result of a repository clone operation."""
    success: bool
    repo_path: str
    commit_sha: str
    error_message: Optional[str] = None


@dataclass
class UpdateResult:
    """Result of a repository update operation."""
    success: bool
    old_commit_sha: str
    new_commit_sha: str
    files_changed: List[str]
    error_message: Optional[str] = None


@dataclass
class FileInfo:
    """File information from discovery operations."""
    path: str
    relative_path: str
    extension: str
    size: int
    last_modified: datetime
    content: Optional[str] = None


@dataclass
class DiscoveryConfig:
    """Configuration for file discovery operations."""
    include_patterns: List[str]
    exclude_patterns: List[str]
    max_file_size: int = 1024 * 1024  # 1MB default
    follow_symlinks: bool = False
    include_hidden: bool = False


@dataclass
class DiscoveryResult:
    """Result of a file discovery operation."""
    files: List[FileInfo]
    total_files: int
    total_size: int
    skipped_files: int
    error_files: List[str]
    discovery_time: float


@dataclass
class GitConfig:
    """Configuration for Git operations."""
    default_branch: str = "main"
    clone_depth: Optional[int] = None
    timeout: int = 300  # 5 minutes
    credentials: Optional[Dict[str, str]] = None


@dataclass
class BranchInfo:
    """Information about a Git branch."""
    name: str
    commit_sha: str
    is_current: bool
    last_commit_date: datetime
    author: str
    message: str


@dataclass
class RepoStats:
    """Statistics about a repository."""
    total_files: int
    total_size: int
    languages: Dict[str, int]  # language -> file count
    last_commit_date: datetime
    commit_count: int
    branch_count: int
