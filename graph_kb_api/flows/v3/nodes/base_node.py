"""
Base workflow node implementation for v3 workflows.

Adapted from v2 base node to work with v3 state structure (BaseCommandState).
Provides proper async handling, service injection, and state management.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from langgraph.errors import GraphInterrupt
from langgraph.types import RunnableConfig

from graph_kb_api.flows.v3.exceptions import ServiceNotAvailableError
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.types import ThreadConfigurable

if TYPE_CHECKING:
    from graph_kb_api.context import AppContext

from graph_kb_api.flows.v3.models.node_models import (
    NodeExecutionResult,
    NodeExecutionStatus,
)
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class BaseWorkflowNodeV3(ABC):
    """
    Base class for all v3 workflow nodes.

    Provides:
    - Proper async/await handling
    - Service injection through LangGraph configuration
    - State management for v3 state structure (BaseCommandState)
    - Error handling with state consistency
    - Progress tracking
    """

    def __init__(self, node_name: str):
        """
        Initialize the base workflow node.

        Args:
            node_name: Unique name for this node
        """
        self.node_name = node_name
        self.logger = EnhancedLogger(f"{__name__}.{node_name}")

    def _setup_execution_context(self, state: Dict[str, Any], services: ServiceRegistry) -> None:
        """
        Setup execution context (logger session).

        Args:
            state: Current workflow state
            services: Injected services
        """
        # Set logger session ID
        logger.set_session_id(state.get("session_id", ""))

    def _get_app_context(self, services: ServiceRegistry) -> Optional[AppContext]:
        """
        Get app_context from services with validation.

        Args:
            services: Injected services

        Returns:
            AppContext instance or None if not available
        """
        return services.get("app_context")

    def _get_graph_kb_facade(self, services: ServiceRegistry) -> Optional[Any]:
        """
        Get GraphKB facade from app_context with validation.

        Args:
            services: Injected services

        Returns:
            GraphKBFacade instance or None if not available
        """
        app_context = self._get_app_context(services)

        if not app_context:
            return None

        if not hasattr(app_context, "graph_kb_facade"):
            return None

        return app_context.graph_kb_facade

    def _require_graph_kb_facade(self, services: ServiceRegistry) -> tuple[Any, NodeExecutionResult | None]:
        """
        Get GraphKB facade or return error result if not available.

        This is a convenience method that returns either:
        - (facade, None) if successful
        - (None, error_result) if facade is not available

        Args:
            services: Injected services

        Returns:
            Tuple of (facade, error_result). Check if facade is None.

        Example:
            facade, error = self._require_graph_kb_facade(services)
            if error:
                return error
            # Use facade...
        """
        app_context: AppContext | None = self._get_app_context(services)
        if not app_context:
            logger.error(f"[{self.node_name}] Application context not available in services")
            return None, NodeExecutionResult.failure(
                "Application context not available",
                metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
            )

        if not app_context.graph_kb_facade:
            logger.error(f"[{self.node_name}] app_context.graph_kb_facade is None")
            return None, NodeExecutionResult.failure(
                "GraphKB facade not initialized",
                metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
            )

        return app_context.graph_kb_facade, None

    def _require_retrieval_service(self, services: ServiceRegistry) -> tuple[Any, NodeExecutionResult | None]:
        """
        Get retrieval service from GraphKB facade or return error result.

        Args:
            services: Injected services

        Returns:
            Tuple of (retrieval_service, error_result). Check if service is None.

        Example:
            retrieval_service, error = self._require_retrieval_service(services)
            if error:
                return error
            # Use retrieval_service...
        """
        facade, error = self._require_graph_kb_facade(services)
        if error:
            return None, error

        if not hasattr(facade, "retrieval_service") or not facade.retrieval_service:
            logger.error(f"[{self.node_name}] GraphKB facade missing retrieval_service")
            return None, NodeExecutionResult.failure(
                "Retrieval service not available in GraphKB facade",
                metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
            )

        return facade.retrieval_service, None

    async def execute(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Execute the workflow node and return the result.

        This is a convenience method that extracts the result from the state update.

        Args:
            state: Current workflow state
            services: Injected services

        Returns:
            Node execution result
        """
        # Execute the node
        result: NodeExecutionResult = await self._execute_async(state, services)
        return result

    async def __call__(self, state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        """
        Execute the workflow node with proper async handling.

        Args:
            state: Current workflow state (v3 BaseCommandState structure)
            config: LangGraph configuration with service injection

        Returns:
            Updated workflow state
        """
        start_time = datetime.now(UTC)

        try:
            # Store config for nodes that need it
            self._config = config

            # Extract services from LangGraph configuration
            services = self._extract_services(config)

            # Update progress
            state = self._update_progress(state)

            # Execute the node logic
            result = await self._execute_async(state, services)

            # Calculate execution time
            execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
            result.execution_time_ms = int(execution_time)

            # Update state with results
            updated_state = self._update_state_with_result(state, result)

            self.logger.info(f"Node {self.node_name} executed successfully in {execution_time:.1f}ms")

            return updated_state

        except GraphInterrupt:
            # GraphInterrupt is raised by interrupt() for human-in-the-loop
            # Let it propagate to LangGraph - this is expected behavior
            raise

        except ServiceNotAvailableError as e:
            # Calculate execution time for error case
            execution_time = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Create specific error result for service unavailability
            error_result: NodeExecutionResult = NodeExecutionResult.failure(
                error_message=str(e),
                error_exception=e,
                metadata={
                    "error_type": "service_unavailable",
                    "service_name": e.service_name,
                    "node_name": e.node_name,
                    "error_context": self._get_error_context(state),
                },
            )
            error_result.execution_time_ms = int(execution_time)

            # Update state with error information
            error_state = self._update_state_with_error(state, error_result)

            self.logger.error(
                f"Node {self.node_name} failed: Required service '{e.service_name}' not available",
                data={"service_name": e.service_name},
            )

            return error_state

        except Exception as e:
            # Calculate execution time for error case
            execution_time: int | float = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Create error result
            error_result: NodeExecutionResult = NodeExecutionResult.failure(
                error_message=str(e),
                error_exception=e,
                metadata={"error_context": self._get_error_context(state)},
            )
            error_result.execution_time_ms = int(execution_time)

            # Update state with error information
            error_state = self._update_state_with_error(state, error_result)

            self.logger.error(
                f"Node {self.node_name} failed after {execution_time:.1f}ms: {e}",
                exc_info=True,  # Include full traceback
            )

            return error_state

    @abstractmethod
    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Execute the node's core logic asynchronously.

        Args:
            state: Current workflow state
            services: Injected services from LangGraph configuration

        Returns:
            Node execution result
        """
        pass

    def _extract_services(self, config: Optional[RunnableConfig]) -> ServiceRegistry:
        """
        Extract services from LangGraph configuration.

        Args:
            config: LangGraph configuration

        Returns:
            Dictionary of available services
        """
        if not config:
            return {}

        # Extract service configuration from LangGraph config
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))

        # Support both v2 and v3 service config structures
        services: ServiceRegistry = configurable.get("services", {})
        if not services:
            service_config = configurable.get("service_config", {})
            services = {
                "app_context": service_config.get("app_context"),
            }

        return cast(ServiceRegistry, services)

    def _update_progress(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update progress tracking in state.

        Args:
            state: Current workflow state

        Returns:
            Updated state
        """
        state = dict(state)  # Create a copy
        state["progress_step"] = state.get("progress_step", 0) + 1
        return state

    def _update_state_with_result(self, state: Dict[str, Any], result: NodeExecutionResult) -> Dict[str, Any]:
        """
        Build partial state update from node execution result.

        Returns ONLY the changed keys so LangGraph can apply reducers correctly.
        Returning the full state would bypass the Annotated reducers.

        Args:
            state: Current workflow state (used for context, not modified)
            result: Node execution result

        Returns:
            Partial state update dict for LangGraph to merge
        """
        update: Dict[str, Any] = {}

        # Update status based on result
        if result.status == NodeExecutionStatus.SUCCESS:
            # Success - return only the output keys for LangGraph to merge
            if result.output:
                for key, value in result.output.items():
                    # Only protect the immutable workflow ID
                    # user_id and session_id can be set by nodes if needed
                    if key != "workflow_id":
                        update[key] = value

            # Clear any previous errors if we have output
            if state.get("error") and update:
                update["error"] = {}

        elif result.status == NodeExecutionStatus.FAILURE:
            # Failure - set error fields and workflow status
            if result.error:
                update["error"] = {
                    "phase": self.node_name.replace("_phase", ""),
                    "message": str(result.error),
                    "code": (result.metadata or {}).get("error_type", type(result.error).__name__),
                }
            update["workflow_status"] = "error"

        return update

    def _update_state_with_error(self, state: Dict[str, Any], error_result: NodeExecutionResult) -> Dict[str, Any]:
        """
        Build partial state update with error information.

        Returns ONLY the changed keys so LangGraph can apply reducers correctly.

        Args:
            state: Current workflow state (used for context, not modified)
            error_result: Error execution result

        Returns:
            Partial state update dict with error and workflow_status
        """
        update: Dict[str, Any] = {}

        # Set error fields in the standard error dict format
        if error_result.error:
            update["error"] = {
                "phase": self.node_name.replace("_phase", ""),
                "message": str(error_result.error),
                "code": (error_result.metadata or {}).get("error_type", type(error_result.error).__name__),
            }
        else:
            update["error"] = {
                "phase": self.node_name.replace("_phase", ""),
                "message": "Unknown error",
                "code": "UnknownError",
            }

        # Set workflow status to error so router can halt
        update["workflow_status"] = "error"

        return update

    def _get_error_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get error context for debugging.

        Args:
            state: Current workflow state

        Returns:
            Error context information
        """
        return {
            "workflow_id": state.get("workflow_id"),
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "repo_id": state.get("repo_id"),
            "node_name": self.node_name,
            "progress_step": state.get("progress_step", 0),
        }

    async def _get_service(self, services: ServiceRegistry, service_name: str, required: bool = True) -> Optional[Any]:
        """
        Get a service from the service registry.

        Args:
            services: Services dictionary from configuration
            service_name: Name of the service to retrieve
            required: Whether the service is required

        Returns:
            Service instance or None if not required and not found

        Raises:
            ServiceNotAvailableError: If required service is not available
        """
        service = services.get(service_name)

        if service is None and required:
            raise ServiceNotAvailableError(service_name, self.node_name)

        return service

    async def _call_service_async(self, service: Any, method_name: str, *args, **kwargs) -> Any:
        """
        Call a service method with proper async handling.

        Args:
            service: Service instance
            method_name: Method name to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Service method result
        """
        if not hasattr(service, method_name):
            raise Exception(f"Service {type(service).__name__} has no method '{method_name}'")

        method = getattr(service, method_name)

        # Handle both sync and async methods
        if asyncio.iscoroutinefunction(method):
            return await method(*args, **kwargs)
        else:
            return method(*args, **kwargs)

    def _construct_thread_id(self, state: Dict[str, Any]) -> str:
        """
        Construct thread_id from state using the same format as create_thread_config.

        Thread IDs follow the format: {user_id}_{session_id}_{repo_url_or_id}
        The repo_url_or_id is the original input (not the resolved repo_id) to ensure
        consistency with the thread_id created at workflow start.

        Args:
            state: Current workflow state

        Returns:
            Thread ID string
        """
        user_id = state.get("user_id", "default")
        session_id = state.get("session_id", "default")
        # Use repo_url_or_id (original input) not repo_id (resolved value)
        repo_url_or_id = state.get("repo_url_or_id", "")

        # Construct thread_id using the same format as create_thread_config
        thread_id_parts = [user_id, session_id]
        if repo_url_or_id:
            thread_id_parts.append(repo_url_or_id)

        return "_".join(thread_id_parts)
