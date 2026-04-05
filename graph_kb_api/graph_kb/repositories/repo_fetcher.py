"""Repository fetching and management for the graph knowledge base.

This module handles cloning, updating, and managing GitHub repositories
for ingestion into the graph knowledge base.
"""

import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.base import IngestionConfig

logger = EnhancedLogger(__name__)


@dataclass
class RepoInfo:
    """Information about a cloned/updated repository."""

    repo_id: str
    local_path: str
    commit_sha: str
    branch: str
    git_url: str


@dataclass
class ChangedFiles:
    """Files changed between two commits."""

    changed: List[str]
    deleted: List[str]


class RepoFetcherError(Exception):
    """Base exception for RepoFetcher errors."""

    pass


class InvalidURLError(RepoFetcherError):
    """Raised when the repository URL is invalid."""

    pass


class AuthenticationError(RepoFetcherError):
    """Raised when authentication fails."""

    pass


class RepoTooLargeError(RepoFetcherError):
    """Raised when repository exceeds size limit."""

    pass


class CloneError(RepoFetcherError):
    """Raised when cloning fails."""

    pass


class UpdateError(RepoFetcherError):
    """Raised when updating fails."""

    pass


class RepoFetcher(ABC):
    """Abstract base class for repository fetching and management.

    This interface defines the contract for handling repository operations
    including cloning, updating, and managing GitHub repositories.
    """

    @abstractmethod
    def validate_url(self, repo_url: str) -> Tuple[str, str]:
        """Validate a repository URL.

        Args:
            repo_url: The repository URL to validate.

        Returns:
            Tuple of (owner, repo_name).

        Raises:
            InvalidURLError: If the URL is not valid.
        """
        pass

    @abstractmethod
    def create_repo_id(self, repo_url: str) -> str:
        """Create a unique repository ID from the URL.

        Args:
            repo_url: The repository URL.

        Returns:
            A unique identifier for the repository.
        """
        pass

    @abstractmethod
    def clone_repo(
        self,
        repo_url: str,
        branch: str = "main",
        auth_token: Optional[str] = None,
    ) -> RepoInfo:
        """Clone a repository.

        Args:
            repo_url: Repository URL.
            branch: Branch to clone (default: main).
            auth_token: Optional authentication token for private repos.

        Returns:
            RepoInfo with details about the cloned repository.

        Raises:
            InvalidURLError: If the URL is invalid.
            AuthenticationError: If authentication fails.
            RepoTooLargeError: If repository exceeds size limit.
            CloneError: If cloning fails for other reasons.
        """
        pass

    @abstractmethod
    def update_repo(
        self,
        repo_id: str,
        branch: str = "main",
        auth_token: Optional[str] = None,
    ) -> RepoInfo:
        """Update an existing repository with latest changes.

        Args:
            repo_id: Repository identifier.
            branch: Branch to update.
            auth_token: Optional authentication token.

        Returns:
            RepoInfo with updated details.

        Raises:
            UpdateError: If the repository doesn't exist or update fails.
        """
        pass

    @abstractmethod
    def repo_exists(self, repo_id: str) -> bool:
        """Check if a repository exists locally.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if the repository exists and is valid.
        """
        pass

    @abstractmethod
    def delete_repo(self, repo_id: str) -> bool:
        """Delete a repository from local storage.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if deleted, False if not found.
        """
        pass


class GitRepoFetcher(RepoFetcher):
    """Handles cloning and updating GitHub repositories.

    This class provides functionality to:
    - Clone repositories using shallow clone for efficiency
    - Update existing repositories with latest changes
    - Get list of changed files between commits
    - Validate repository URLs and sizes
    """

    # Regex pattern for valid GitHub HTTPS URLs
    GITHUB_URL_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$"
    )
    # Regex pattern for GitHub SSH URLs: git@github.com:owner/repo.git
    GITHUB_SSH_PATTERN = re.compile(
        r"^git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$"
    )

    @classmethod
    def _normalize_ssh_to_https(cls, repo_url: str) -> str:
        """Convert SSH URL to HTTPS if needed; return unchanged otherwise."""
        m = cls.GITHUB_SSH_PATTERN.match(repo_url.strip())
        if m:
            return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
        return repo_url

    def __init__(
        self,
        storage_path: str = "/data/repos",
        config: Optional[IngestionConfig] = None,
    ):
        """Initialize the RepoFetcher.

        Args:
            storage_path: Base path for storing cloned repositories.
            config: Ingestion configuration with size limits.
        """
        self.storage_path = Path(storage_path)
        self.config = config or IngestionConfig()
        self._ensure_storage_path()

    def _ensure_storage_path(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def validate_url(self, repo_url: str) -> Tuple[str, str]:
        """Validate a GitHub repository URL (HTTPS or SSH format).

        Args:
            repo_url: The repository URL to validate.

        Returns:
            Tuple of (owner, repo_name).

        Raises:
            InvalidURLError: If the URL is not a valid GitHub repository URL.
        """
        normalized = self._normalize_ssh_to_https(repo_url)
        match = self.GITHUB_URL_PATTERN.match(normalized)
        if not match:
            raise InvalidURLError(
                f"Invalid GitHub URL: {repo_url}. "
                "Expected format: https://github.com/owner/repo or git@github.com:owner/repo"
            )
        return match.group(1), match.group(2)

    def create_repo_id(self, repo_url: str) -> str:
        """Create a unique repository ID from the URL.

        Args:
            repo_url: The repository URL.

        Returns:
            A unique identifier for the repository.
        """
        owner, repo_name = self.validate_url(repo_url)
        return f"{owner}_{repo_name}"

    def get_repo_path(self, repo_id: str, commit_sha: Optional[str] = None) -> Path:
        """Get the local path for a repository.

        Args:
            repo_id: The repository identifier.
            commit_sha: Optional commit SHA for versioned path.

        Returns:
            Path to the repository directory.
        """
        if commit_sha:
            return self.storage_path / repo_id / commit_sha
        return self.storage_path / repo_id / "latest"

    def _normalize_url(self, repo_url: str) -> str:
        """Normalize a GitHub URL to HTTPS format.

        Args:
            repo_url: The repository URL.

        Returns:
            Normalized HTTPS URL.
        """
        owner, repo_name = self.validate_url(repo_url)
        return f"https://github.com/{owner}/{repo_name}.git"

    def _get_authenticated_url(
        self, repo_url: str, auth_token: Optional[str] = None
    ) -> str:
        """Get URL with authentication token embedded.

        Args:
            repo_url: The repository URL.
            auth_token: GitHub Personal Access Token or App token.

        Returns:
            URL with authentication if token provided.
        """
        normalized = self._normalize_url(repo_url)
        if auth_token:
            # Insert token into URL: https://token@github.com/...
            return normalized.replace("https://", f"https://{auth_token}@")
        return normalized

    def _get_repo_size_mb(self, repo: Repo) -> float:
        """Estimate repository size in MB.

        Args:
            repo: Git repository object.

        Returns:
            Estimated size in megabytes.
        """
        repo_path = Path(repo.working_dir)
        total_size = sum(f.stat().st_size for f in repo_path.rglob("*") if f.is_file())
        return total_size / (1024 * 1024)

    def clone_repo(
        self,
        repo_url: str,
        branch: str = "main",
        auth_token: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        _fallback_attempted: bool = False,
    ) -> RepoInfo:
        """Clone a repository using shallow clone.
            branch: Branch to clone (default: main).
            auth_token: Optional authentication token for private repos.

        Returns:
            RepoInfo with details about the cloned repository.

        Raises:
            InvalidURLError: If the URL is invalid.
            AuthenticationError: If authentication fails.
            RepoTooLargeError: If repository exceeds size limit.
            CloneError: If cloning fails for other reasons.
        """
        # Validate URL
        self.validate_url(repo_url)
        repo_id = self.create_repo_id(repo_url)

        # Get authenticated URL
        clone_url = self._get_authenticated_url(repo_url, auth_token)

        # Prepare local path
        local_path = self.get_repo_path(repo_id)

        # Remove existing directory if present
        if local_path.exists():
            import stat

            def _on_rm_error(func, path, exc_info):
                """Handle read-only files on Windows (e.g. .git pack files)."""
                os.chmod(path, stat.S_IWRITE)
                func(path)

            shutil.rmtree(local_path, onerror=_on_rm_error)

        # Ensure parent directory exists (but NOT the target — git clone creates it)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(f"Cloning repository {repo_url} to {local_path}")

            # Shallow clone with single branch
            clone_kwargs = dict(
                branch=branch,
                depth=1,
                single_branch=True,
            )
            if progress_callback is not None:
                from graph_kb_api.graph_kb.repositories.clone_progress import (
                    CloneProgressHandler,
                )

                clone_kwargs["progress"] = CloneProgressHandler(progress_callback)

            repo = Repo.clone_from(
                clone_url,
                local_path,
                **clone_kwargs,
            )

            # Check repository size
            repo_size = self._get_repo_size_mb(repo)
            if repo_size > self.config.max_repo_size_mb:
                # Clean up and raise error
                shutil.rmtree(local_path)
                raise RepoTooLargeError(
                    f"Repository size ({repo_size:.1f} MB) exceeds limit "
                    f"({self.config.max_repo_size_mb} MB)"
                )

            # Get commit SHA
            commit_sha = repo.head.commit.hexsha

            logger.info(f"Successfully cloned {repo_url} at commit {commit_sha[:8]}")

            return RepoInfo(
                repo_id=repo_id,
                local_path=str(local_path),
                commit_sha=commit_sha,
                branch=branch,
                git_url=self._normalize_url(repo_url),
            )

        except GitCommandError as e:
            # Clean up on failure
            if local_path.exists():
                import stat as _stat

                def _on_rm_error_cleanup(func, path, exc_info):
                    os.chmod(path, _stat.S_IWRITE)
                    func(path)

                shutil.rmtree(local_path, onerror=_on_rm_error_cleanup)

            error_msg = str(e)
            stderr = getattr(e, "stderr", "") or ""
            # GitPython may embed stderr in the string repr; combine both
            # for reliable keyword detection.
            combined = f"{error_msg} {stderr}".lower()

            logger.warning(
                "Git clone failed | repo=%s branch=%s exit_code=%s stderr=%r",
                repo_url,
                branch,
                getattr(e, "status", "?"),
                stderr[:500] if stderr else "(empty)",
            )

            if (
                "authentication failed" in combined
                or "could not read username" in combined
            ):
                raise AuthenticationError(
                    f"Authentication failed for {repo_url}. "
                    "Please provide a valid access token."
                )

            # Detect branch-not-found and retry with fallback branch.
            # Check both stderr and the full error message since GitPython
            # may place the remote error in either location.
            branch_not_found = (
                "remote branch" in combined and "not found" in combined
            ) or (f"remote branch {branch} not found" in combined)

            if not _fallback_attempted and branch_not_found:
                fallback = "master" if branch == "main" else "main"
                logger.info(f"Branch '{branch}' not found, retrying with '{fallback}'")
                try:
                    return self.clone_repo(
                        repo_url=repo_url,
                        branch=fallback,
                        auth_token=auth_token,
                        progress_callback=progress_callback,
                        _fallback_attempted=True,
                    )
                except (CloneError, AuthenticationError):
                    raise CloneError(
                        f"Branch '{branch}' not found and fallback "
                        f"'{fallback}' also failed for {repo_url}"
                    )

            # When a progress callback is used, GitPython's stderr may be
            # consumed by the progress handler, leaving e.stderr empty.
            # In that case we can't distinguish "branch not found" from
            # other exit-128 errors.  As a safety net, attempt the
            # alternate default branch whenever the failure is ambiguous.
            status = getattr(e, "status", None)
            if (
                not _fallback_attempted
                and not branch_not_found
                and status == 128
                and branch in ("main", "master")
            ):
                fallback = "master" if branch == "main" else "main"
                logger.info(
                    "Ambiguous exit-128 failure (stderr may have been consumed "
                    "by progress handler). Trying fallback branch '%s'",
                    fallback,
                )
                try:
                    return self.clone_repo(
                        repo_url=repo_url,
                        branch=fallback,
                        auth_token=auth_token,
                        progress_callback=progress_callback,
                        _fallback_attempted=True,
                    )
                except (CloneError, AuthenticationError):
                    # Both branches failed with exit 128 and empty stderr.
                    # This is almost always an auth failure for private repos
                    # where the progress handler consumed stderr.
                    is_github = "github.com" in repo_url.lower()
                    token_hint = (
                        " Set the GITHUB_TOKEN environment variable to a "
                        "personal access token with 'repo' scope."
                        if is_github
                        else " Ensure a valid access token is configured."
                    )
                    raise AuthenticationError(
                        f"Could not clone {repo_url} — the repository may be "
                        f"private or the access token is missing/invalid.{token_hint}"
                    )

            if "not found" in combined or "does not exist" in combined:
                raise CloneError(f"Repository not found: {repo_url}")
            else:
                raise CloneError(f"Failed to clone repository: {error_msg}")

    def update_repo(
        self,
        repo_id: str,
        branch: str = "main",
        auth_token: Optional[str] = None,
    ) -> RepoInfo:
        """Update an existing repository with latest changes.

        Args:
            repo_id: Repository identifier.
            branch: Branch to update.
            auth_token: Optional authentication token.

        Returns:
            RepoInfo with updated details.

        Raises:
            UpdateError: If the repository doesn't exist or update fails.
        """
        local_path = self.get_repo_path(repo_id)

        if not local_path.exists():
            raise UpdateError(f"Repository not found at {local_path}")

        try:
            repo = Repo(local_path)
        except InvalidGitRepositoryError:
            raise UpdateError(f"Invalid git repository at {local_path}")

        try:
            # Get the remote URL for RepoInfo
            origin = repo.remote("origin")
            git_url = origin.url

            # If no branch specified, use the current branch
            if not branch or branch == "main":
                try:
                    # Get the current branch name
                    current_branch = repo.active_branch.name
                    logger.info(f"Using current branch: {current_branch}")
                    branch = current_branch
                except Exception as e:
                    logger.warning(
                        f"Could not determine current branch: {e}, using 'main'"
                    )
                    branch = "main"

            # Update authentication if token provided
            if auth_token:
                # Parse and update remote URL with token
                parsed = urlparse(git_url)
                if parsed.scheme in ("http", "https"):
                    # Use hostname instead of netloc to avoid duplicating existing tokens
                    # netloc includes username/password, hostname is just the host
                    host = parsed.hostname or parsed.netloc
                    port_str = f":{parsed.port}" if parsed.port else ""
                    new_url = (
                        f"{parsed.scheme}://{auth_token}@{host}{port_str}{parsed.path}"
                    )
                    origin.set_url(new_url)

            logger.info(f"Fetching updates for {repo_id}")

            # Fetch latest changes for the specific branch
            origin.fetch(branch, depth=1)

            # Reset to remote branch using git command directly
            repo.git.reset("--hard", f"origin/{branch}")

            # Get new commit SHA
            commit_sha = repo.head.commit.hexsha

            # Restore original URL if we modified it
            if auth_token:
                origin.set_url(git_url)

            logger.info(f"Successfully updated {repo_id} to commit {commit_sha[:8]}")

            return RepoInfo(
                repo_id=repo_id,
                local_path=str(local_path),
                commit_sha=commit_sha,
                branch=branch,
                git_url=git_url,
            )

        except GitCommandError as e:
            error_msg = str(e)
            if "Authentication failed" in error_msg:
                raise AuthenticationError(
                    f"Authentication failed for {repo_id}. "
                    "Please provide a valid access token."
                )
            raise UpdateError(f"Failed to update repository: {error_msg}")

    def get_changed_files(
        self,
        repo_id: str,
        from_commit: str,
        to_commit: str,
    ) -> ChangedFiles:
        """Get list of changed and deleted files between commits.

        Args:
            repo_id: Repository identifier.
            from_commit: Starting commit SHA.
            to_commit: Ending commit SHA.

        Returns:
            ChangedFiles with lists of changed and deleted files.

        Raises:
            UpdateError: If the repository doesn't exist or commits are invalid.
        """
        local_path = self.get_repo_path(repo_id)

        if not local_path.exists():
            raise UpdateError(f"Repository not found at {local_path}")

        try:
            repo = Repo(local_path)
        except InvalidGitRepositoryError:
            raise UpdateError(f"Invalid git repository at {local_path}")

        try:
            # Unshallow if needed to access older commits
            if repo.head.is_detached or len(list(repo.iter_commits())) <= 1:
                try:
                    repo.remote("origin").fetch(unshallow=True)
                except GitCommandError:
                    # May already be unshallowed or have full history
                    pass

            # Get diff between commits
            diff = repo.git.diff(
                from_commit,
                to_commit,
                name_status=True,
            )

            changed = []
            deleted = []

            for line in diff.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                status = parts[0]
                file_path = parts[1]

                if status == "D":
                    deleted.append(file_path)
                else:
                    # A (added), M (modified), R (renamed), C (copied)
                    changed.append(file_path)

            logger.info(
                f"Found {len(changed)} changed and {len(deleted)} deleted files "
                f"between {from_commit[:8]} and {to_commit[:8]}"
            )

            return ChangedFiles(changed=changed, deleted=deleted)

        except GitCommandError as e:
            raise UpdateError(f"Failed to get changed files: {str(e)}")

    def repo_exists(self, repo_id: str) -> bool:
        """Check if a repository exists locally.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if the repository exists and is valid.
        """
        local_path = self.get_repo_path(repo_id)
        if not local_path.exists():
            return False

        try:
            Repo(local_path)
            return True
        except InvalidGitRepositoryError:
            return False

    def delete_repo(self, repo_id: str) -> bool:
        """Delete a repository from local storage.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if deleted, False if not found.
        """
        import stat

        def _on_rm_error(func, path, exc_info):
            """Handle read-only files on Windows (e.g. .git pack files)."""
            os.chmod(path, stat.S_IWRITE)
            func(path)

        repo_base = self.storage_path / repo_id
        if repo_base.exists():
            shutil.rmtree(repo_base, onerror=_on_rm_error)
            logger.info(f"Deleted repository {repo_id}")
            return True
        return False
