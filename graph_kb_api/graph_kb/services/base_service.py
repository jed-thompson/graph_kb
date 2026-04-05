"""Base service class for Graph KB services.

This module provides a base class with common functionality shared across
all Graph KB services, including repository validation, metadata access,
and common error handling patterns.
"""

from abc import ABC
from typing import Literal, Optional, Union

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models import RepositoryNotFoundError, RepositoryNotReadyError
from ..models.enums import RepoStatus
from ..storage import MetadataStore

logger = EnhancedLogger(__name__)

# Validation strategy types
ValidationStrategy = Literal["strict", "bool", "message"]


class BaseGraphKBService(ABC):
    """Base class for Graph KB services with common functionality.

    This base class provides:
    - Repository validation (unified method with multiple strategies)
    - Metadata store access (status, paths, etc.)
    - Common error handling patterns

    **Usage**:
        Services should inherit from this class:

        >>> class MyService(BaseGraphKBService):
        ...     def __init__(self, metadata_store, my_adapter):
        ...         super().__init__(metadata_store)
        ...         self._my_adapter = my_adapter
        ...         # Service-specific initialization

    **Validation Strategies**:
        Use validate_repository() with different strategies:
        - strategy="strict": Raises exceptions (for query/retrieval)
        - strategy="bool": Returns boolean (for analysis)
        - strategy="message": Returns error message (for visualization)
    """

    def __init__(self, metadata_store: MetadataStore):
        """Initialize base service.

        Args:
            metadata_store: Store for repository metadata.
        """
        self._metadata_store = metadata_store

    # =========================================================================
    # Repository Validation (Unified with Multiple Strategies)
    # =========================================================================

    def validate_repository(
        self, repo_id: str, strategy: ValidationStrategy = "strict"
    ) -> Union[None, bool, str]:
        """Validate repository with configurable strategy.

        This unified validation method supports three strategies:

        1. **"strict"**: Raises exceptions for invalid repositories
           - Use for: Query/retrieval services that need to fail fast
           - Returns: None (or raises exception)
           - Raises: RepositoryNotFoundError, RepositoryNotReadyError

        2. **"bool"**: Returns boolean validation result
           - Use for: Analysis services with fallback logic
           - Returns: True if valid, False otherwise

        3. **"message"**: Returns user-friendly error message
           - Use for: Visualization services and UI handlers
           - Returns: None if valid, error message string otherwise

        Args:
            repo_id: Repository identifier.
            strategy: Validation strategy to use ("strict", "bool", or "message").

        Returns:
            - None if strategy="strict" and valid (or raises exception)
            - bool if strategy="bool" (True=valid, False=invalid)
            - Optional[str] if strategy="message" (None=valid, str=error message)

        Raises:
            RepositoryNotFoundError: If strategy="strict" and repo doesn't exist.
            RepositoryNotReadyError: If strategy="strict" and repo is not ready.
        """
        try:
            repo = self._metadata_store.get_repo(repo_id)

            # Check if repository exists
            if repo is None:
                if strategy == "strict":
                    raise RepositoryNotFoundError(
                        f"Repository '{repo_id}' is not indexed."
                    )
                elif strategy == "bool":
                    return False
                else:  # message
                    return (
                        f"Repository '{repo_id}' not found. "
                        f"Use `/list_repos` to see available repositories."
                    )

            # Check if repository is ready
            if repo.status != RepoStatus.READY:
                if strategy == "strict":
                    raise RepositoryNotReadyError(repo_id, repo.status)
                elif strategy == "bool":
                    # For bool strategy, also accept "completed" status
                    return repo.status.value in ["completed", "ready"]
                else:  # message
                    return (
                        f"Repository '{repo_id}' is {repo.status.value}. "
                        f"Please wait for indexing to complete."
                    )

            # Repository is valid
            if strategy == "strict":
                return None
            elif strategy == "bool":
                return True
            else:  # message
                return None

        except (RepositoryNotFoundError, RepositoryNotReadyError):
            # Re-raise these for strict strategy
            if strategy == "strict":
                raise
            # For other strategies, handle as validation failure
            elif strategy == "bool":
                return False
            else:  # message
                import sys

                e = sys.exc_info()[1]
                return f"Repository validation failed: {str(e)}"
        except Exception as e:
            logger.error(f"Failed to validate repo {repo_id}: {e}")
            if strategy == "strict":
                raise RepositoryNotFoundError(
                    f"Failed to validate repository: {str(e)}"
                )
            elif strategy == "bool":
                logger.warning(f"Repository validation failed for {repo_id}: {e}")
                return False
            else:  # message
                return f"Failed to validate repository: {str(e)}"

    # =========================================================================
    # Repository Metadata Access
    # =========================================================================

    def get_repo_local_path(self, repo_id: str) -> Optional[str]:
        """Get the local file path for a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            Local path if found, None otherwise.
        """
        try:
            repo = self._metadata_store.get_repo(repo_id)
            return repo.local_path if repo else None
        except Exception as e:
            logger.warning(f"Failed to get local path for {repo_id}: {e}")
            return None

    def get_repo_status(self, repo_id: str) -> Optional[RepoStatus]:
        """Get the current status of a repository.

        Args:
            repo_id: Repository identifier.

        Returns:
            Repository status or None if not found.
        """
        try:
            repo = self._metadata_store.get_repo(repo_id)
            return repo.status if repo else None
        except Exception as e:
            logger.warning(f"Failed to get status for {repo_id}: {e}")
            return None

    def is_repo_ready(self, repo_id: str) -> bool:
        """Check if a repository is ready for operations.

        This is a convenience method that combines status checking
        with a simple boolean return.

        Args:
            repo_id: Repository identifier.

        Returns:
            True if repository is ready, False otherwise.
        """
        status = self.get_repo_status(repo_id)
        return status == RepoStatus.READY

    # =========================================================================
    # Error Handling Helpers
    # =========================================================================

    def _log_operation_start(self, operation: str, **kwargs) -> None:
        """Log the start of an operation with context.

        Args:
            operation: Name of the operation.
            **kwargs: Additional context to log.

        Example:
            >>> self._log_operation_start("retrieve_context", repo_id=repo_id, query=query)
        """
        logger.info(f"Starting {operation}", data=kwargs)

    def _log_operation_complete(self, operation: str, **kwargs) -> None:
        """Log the completion of an operation with results.

        Args:
            operation: Name of the operation.
            **kwargs: Results or metrics to log.

        Example:
            >>> self._log_operation_complete("retrieve_context", results_count=len(results))
        """
        logger.info(f"Completed {operation}", data=kwargs)

    def _log_operation_error(self, operation: str, error: Exception, **kwargs) -> None:
        """Log an operation error with context.

        Args:
            operation: Name of the operation.
            error: The exception that occurred.
            **kwargs: Additional context to log.

        Example:
            >>> except Exception as e:
            ...     self._log_operation_error("retrieve_context", e, repo_id=repo_id)
        """
        logger.error(
            f"Failed {operation}: {error}",
            data={"error_type": type(error).__name__, **kwargs},
            exc_info=True,
        )
