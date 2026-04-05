"""
Exceptions for v3 workflow system.

This module defines custom exceptions used throughout the v3 workflow framework,
providing more specific error types than generic exceptions.
"""


class WorkflowError(Exception):
    """
    Base exception for all workflow-related errors.

    All workflow-specific exceptions should inherit from this base class
    to allow for easy catching of workflow-related errors.
    """
    pass


class ServiceNotAvailableError(WorkflowError):
    """
    Exception raised when a required service is not available.

    This is raised by BaseWorkflowNodeV3._get_service() when a required
    service is not found in the service registry.
    """

    def __init__(self, service_name: str, node_name: str = None):
        """
        Initialize the exception.

        Args:
            service_name: Name of the missing service
            node_name: Optional name of the node that requires the service
        """
        self.service_name = service_name
        self.node_name = node_name

        if node_name:
            message = f"Required service '{service_name}' not available for node '{node_name}'"
        else:
            message = f"Required service '{service_name}' not available"

        super().__init__(message)


class WorkflowStateError(WorkflowError):
    """
    Exception raised when workflow state is invalid or corrupted.

    This can occur when required state fields are missing or have
    invalid values.
    """

    def __init__(self, message: str, state_field: str = None):
        """
        Initialize the exception.

        Args:
            message: Error message
            state_field: Optional name of the problematic state field
        """
        self.state_field = state_field
        super().__init__(message)


class WorkflowExecutionError(WorkflowError):
    """
    Exception raised when workflow execution fails.

    This is a general exception for workflow execution failures that
    don't fit into more specific categories.
    """
    pass


class WorkflowTimeoutError(WorkflowError):
    """
    Exception raised when workflow execution times out.

    This can occur when a workflow or node takes longer than the
    configured timeout period.
    """

    def __init__(self, message: str, timeout_seconds: float = None):
        """
        Initialize the exception.

        Args:
            message: Error message
            timeout_seconds: Optional timeout value that was exceeded
        """
        self.timeout_seconds = timeout_seconds
        super().__init__(message)
