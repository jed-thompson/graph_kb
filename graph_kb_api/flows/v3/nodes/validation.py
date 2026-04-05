"""
Shared validation nodes for LangGraph v3 workflows.

These nodes provide common validation functionality including input validation
and repository validation that can be reused across different workflows.

All nodes follow LangGraph conventions:
- Nodes are callable objects (implement __call__)
- Nodes take state and return state updates
- Nodes are stateless (configuration in __init__, no mutable state)
"""

import datetime
from typing import Any, Dict, Optional

from langgraph.types import RunnableConfig

from graph_kb_api.flows.v3.state.common import BaseCommandState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class InputValidationNode:
    """
    Validates basic input requirements for workflows.

    This node checks that required fields are present and properly formatted.
    It follows LangGraph conventions as a callable object that takes state
    and returns state updates.

    Configuration:
        required_fields: List of field names that must be present in state

    Example:
        >>> node = InputValidationNode()
        >>> result = await node(state)
    """

    def __init__(self, required_fields: Optional[list] = None):
        """
        Initialize input validation node.

        Args:
            required_fields: List of required field names. If None, uses default set.
        """
        self.node_name = "validate_input"
        self.required_fields = required_fields or [
            "user_id",
            "session_id",
            "workflow_id",
            "thread_id",
        ]

    async def __call__(self, state: BaseCommandState) -> Dict[str, Any]:
        """
        Validate basic input requirements.

        Checks:
        - Required fields are present
        - User ID and session ID are valid (non-empty strings)
        - Args are properly formatted

        Args:
            state: Current workflow state

        Returns:
            State updates with validation results
        """
        logger.info("Validating workflow input")

        # Check required fields
        missing_fields = [
            field for field in self.required_fields if not state.get(field)
        ]

        if missing_fields:
            return {
                "error": f"Missing required fields: {', '.join(missing_fields)}",
                "error_type": "validation_error",
                "success": False,
            }

        # Validate user_id format
        user_id = state.get("user_id", "")
        if not user_id or len(user_id.strip()) == 0:
            return {
                "error": "Invalid user_id: cannot be empty",
                "error_type": "validation_error",
                "success": False,
            }

        # Validate session_id format
        session_id = state.get("session_id", "")
        if not session_id or len(session_id.strip()) == 0:
            return {
                "error": "Invalid session_id: cannot be empty",
                "error_type": "validation_error",
                "success": False,
            }

        logger.info("Input validation passed")

        return {
            "input_validated": True,
            "validation_timestamp": datetime.now(UTC).isoformat(),
        }


class RepositoryValidationNode:
    """
    Validates that a repository exists and is ready for operations.

    This node checks repository availability and readiness in the GraphKB system.
    It gracefully handles cases where GraphKB is not available.

    Configuration:
        allow_skip: If True, allows workflow to continue when GraphKB is unavailable
        ready_statuses: List of status values that indicate repository is ready

    Example:
        >>> node = RepositoryValidationNode()
        >>> result = await node(state, config={'configurable': {'services': services}})
    """

    def __init__(self, allow_skip: bool = True, ready_statuses: Optional[list] = None):
        """
        Initialize repository validation node.

        Args:
            allow_skip: If True, allows workflow to continue when GraphKB unavailable
            ready_statuses: List of status values indicating repository is ready
        """
        self.node_name = "repository_validation"
        self.allow_skip = allow_skip
        self.ready_statuses = ready_statuses or ["completed", "ready", "indexed"]

    async def __call__(
        self, state: BaseCommandState, config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Validate repository exists and is ready.

        Checks:
        - Repository ID is provided
        - Repository exists in the system
        - Repository is in a ready state (not indexing, not failed)

        Args:
            state: Current workflow state
            config: LangGraph config containing services in configurable.services

        Returns:
            State updates with validation results
        """
        logger.info("Validating repository")

        # Check if repo_id is provided
        repo_id = state.get("repo_id")
        if not repo_id:
            return {
                "error": "Repository ID not provided",
                "error_type": "validation_error",
                "success": False,
            }

        # Extract services from config
        services = {}
        if config and "configurable" in config:
            services = config["configurable"].get("services", {})

        # Get app context
        app_context = services.get("app_context")
        if not app_context:
            logger.warning("App context not available for repository validation")
            if self.allow_skip:
                return {
                    "repo_validated": False,
                    "repo_validation_skipped": True,
                    "repo_validation_reason": "app_context_not_available",
                }
            else:
                return {
                    "error": "Application context not available",
                    "error_type": "validation_error",
                    "success": False,
                }

        # Check if GraphKB facade is available
        if (
            not hasattr(app_context, "graph_kb_facade")
            or not app_context.graph_kb_facade
        ):
            logger.warning("GraphKB facade not available for repository validation")
            if self.allow_skip:
                return {
                    "repo_validated": False,
                    "repo_validation_skipped": True,
                    "repo_validation_reason": "graph_kb_not_available",
                }
            else:
                return {
                    "error": "GraphKB not available",
                    "error_type": "validation_error",
                    "success": False,
                }

        try:
            # Get repository status from GraphKB
            facade = app_context.graph_kb_facade

            # Check if repository exists
            repo_exists = await self._check_repository_exists(facade, repo_id)

            if not repo_exists:
                return {
                    "error": f"Repository '{repo_id}' not found",
                    "error_type": "repository_not_found",
                    "success": False,
                    "repo_validated": False,
                }

            # Check repository readiness
            repo_ready = await self._check_repository_ready(facade, repo_id)

            if not repo_ready:
                return {
                    "error": f"Repository '{repo_id}' is not ready",
                    "error_type": "repository_not_ready",
                    "success": False,
                    "repo_validated": False,
                }

            logger.info(f"Repository validation passed for: {repo_id}")

            return {
                "repo_validated": True,
                "repo_exists": True,
                "repo_ready": True,
                "validated_repo_id": repo_id,
            }

        except Exception as e:
            logger.error(f"Repository validation failed: {e}")
            return {
                "error": f"Repository validation error: {str(e)}",
                "error_type": "validation_error",
                "success": False,
                "repo_validated": False,
            }

    async def _check_repository_exists(self, facade, repo_id: str) -> bool:
        """
        Check if a repository exists in the GraphKB.

        Args:
            facade: GraphKB facade instance
            repo_id: Repository identifier

        Returns:
            True if repository exists, False otherwise
        """
        try:
            if hasattr(facade, "metadata_store") and facade.metadata_store:
                repo = facade.metadata_store.get_repo(repo_id)
                return repo is not None

            logger.warning(
                f"Cannot verify repository existence for {repo_id}, assuming exists"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking repository existence: {e}")
            return False

    async def _check_repository_ready(self, facade, repo_id: str) -> bool:
        """
        Check if a repository is ready for operations.

        Args:
            facade: GraphKB facade instance
            repo_id: Repository identifier

        Returns:
            True if repository is ready, False otherwise
        """
        try:
            if hasattr(facade, "metadata_store") and facade.metadata_store:
                repo = facade.metadata_store.get_repo(repo_id)
                if repo:
                    status = (
                        repo.status.value
                        if hasattr(repo.status, "value")
                        else str(repo.status)
                    )
                    return status in self.ready_statuses

            logger.warning(
                f"Cannot verify repository readiness for {repo_id}, assuming ready"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking repository readiness: {e}")
            return False
