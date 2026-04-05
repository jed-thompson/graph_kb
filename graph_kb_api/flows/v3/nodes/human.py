"""
Human-in-the-loop nodes for LangGraph v3 workflows.

These nodes provide human interaction capabilities including clarification,
approval, decision-making, error recovery, and configuration collection.

All nodes follow LangGraph conventions:
- Nodes are callable objects (implement __call__)
- Nodes use interrupt() for human-in-the-loop pauses
- Nodes are configurable through constructor parameters
"""

import datetime
from typing import Any, Dict, List, Optional

from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.flows.v3.state.common import BaseCommandState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ClarificationNode:
    """
    Requests clarification from the user for vague or ambiguous input.

    Uses LangGraph's interrupt() to pause execution and wait for user response.

    Configuration:
        default_message: Default clarification message
        suggestions: Default list of clarification suggestions

    Example:
        >>> node = ClarificationNode()
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_message: str = "Your question seems vague. Can you be more specific?",
        suggestions: Optional[List[str]] = None
    ):
        """
        Initialize clarification node.

        Args:
            default_message: Default message to show user
            suggestions: Default clarification suggestions
        """
        self.node_name = "clarification"
        self.default_message = default_message
        self.suggestions = suggestions or [
            'Which specific function or class?',
            'Which file or module?',
            'What specific behavior are you asking about?'
        ]

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Request clarification from user.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with clarified input
        """
        logger.info("Requesting clarification from user")

        # Get the original question or input
        original_input = state.get('original_input') or state.get('query', '')

        # Prepare clarification request
        clarification_request = {
            'message': self.default_message,
            'original_input': original_input,
            'suggestions': self.suggestions,
            'clarification_type': 'vague_question'
        }

        # Use interrupt() to pause and wait for user response
        user_response = interrupt(clarification_request)

        # When resumed, user_response contains the clarification
        refined_input = user_response.get('refined_input', original_input)

        logger.info("Received clarification from user")

        return {
            'refined_question': refined_input,
            'clarification_provided': True,
            'clarification_attempts': state.get('clarification_attempts', 0) + 1,
            'question_clarity': 'clear'
        }


class ApprovalNode:
    """
    Requests approval from the user before proceeding.

    Uses LangGraph's interrupt() to pause execution and wait for approval/rejection.

    Configuration:
        default_message: Default approval message
        options: Available approval options

    Example:
        >>> node = ApprovalNode()
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_message: str = "Please review and approve the following:",
        options: Optional[List[str]] = None
    ):
        """
        Initialize approval node.

        Args:
            default_message: Default message to show user
            options: Available approval options
        """
        self.node_name = "approval"
        self.default_message = default_message
        self.options = options or ['approve', 'reject', 'modify']

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Request approval from user.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with approval decision
        """
        logger.info("Requesting approval from user")

        # Get content to approve
        content_to_approve = state.get('generated_content') or state.get('preview_data')

        # Prepare approval request
        approval_request = {
            'message': self.default_message,
            'content': content_to_approve,
            'options': self.options,
            'approval_type': 'content_review'
        }

        # Use interrupt() to pause and wait for user decision
        user_decision = interrupt(approval_request)

        # Extract decision
        decision = user_decision.get('decision', 'reject')
        feedback = user_decision.get('feedback', '')

        logger.info(f"Received approval decision: {decision}")

        return {
            'user_approved': decision == 'approve',
            'user_decision': decision,
            'user_feedback': feedback,
            'approval_timestamp': datetime.now(UTC).isoformat()
        }


class DecisionNode:
    """
    Requests a decision from the user with multiple options.

    Uses LangGraph's interrupt() to pause execution and wait for user choice.

    Configuration:
        default_message: Default decision message
        default_options: Default decision options

    Example:
        >>> node = DecisionNode()
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_message: str = "Please make a decision:",
        default_options: Optional[List[str]] = None
    ):
        """
        Initialize decision node.

        Args:
            default_message: Default message to show user
            default_options: Default decision options
        """
        self.node_name = "decision"
        self.default_message = default_message
        self.default_options = default_options or ['continue', 'cancel']

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Request decision from user.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with user decision
        """
        logger.info("Requesting decision from user")

        # Get decision context
        decision_context = state.get('decision_context', {})
        options = decision_context.get('options', self.default_options)
        message = decision_context.get('message', self.default_message)

        # Prepare decision request
        decision_request = {
            'message': message,
            'options': options,
            'context': decision_context,
            'decision_type': 'user_choice'
        }

        # Use interrupt() to pause and wait for user decision
        user_response = interrupt(decision_request)

        # Extract decision
        selected_option = user_response.get('selected_option', options[0] if options else 'cancel')
        additional_input = user_response.get('additional_input', '')

        logger.info(f"Received user decision: {selected_option}")

        return {
            'user_decision': selected_option,
            'user_additional_input': additional_input,
            'decision_made': True,
            'decision_timestamp': datetime.now(UTC).isoformat()
        }


class ErrorRecoveryNode:
    """
    Requests user decision on how to handle an error.

    Uses LangGraph's interrupt() to pause execution and present error recovery options.

    Configuration:
        default_message: Default error message template
        recovery_options: Available recovery options

    Example:
        >>> node = ErrorRecoveryNode()
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_message: str = "An error occurred: {error}",
        recovery_options: Optional[List[str]] = None
    ):
        """
        Initialize error recovery node.

        Args:
            default_message: Default error message template
            recovery_options: Available recovery options
        """
        self.node_name = "error_recovery"
        self.default_message = default_message
        self.recovery_options = recovery_options or ['retry', 'skip', 'abort']

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Request error recovery decision from user.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with recovery decision
        """
        logger.info("Requesting error recovery decision from user")

        # Get error information
        error_info = state.get('error_info', {})
        error_message = error_info.get('error_message', 'An error occurred')

        # Prepare error recovery request
        recovery_request = {
            'message': self.default_message.format(error=error_message),
            'error_details': error_info,
            'options': self.recovery_options,
            'recovery_type': 'error_handling'
        }

        # Use interrupt() to pause and wait for user decision
        user_response = interrupt(recovery_request)

        # Extract recovery decision
        recovery_action = user_response.get('recovery_action', 'abort')

        logger.info(f"Received error recovery decision: {recovery_action}")

        return {
            'user_error_decision': recovery_action,
            'error_recovery_attempted': True,
            'recovery_timestamp': datetime.now(UTC).isoformat()
        }


class ConfigurationNode:
    """
    Requests configuration input from the user.

    Uses LangGraph's interrupt() to pause execution and collect configuration parameters.

    Configuration:
        default_message: Default configuration message
        default_fields: Default configuration fields

    Example:
        >>> node = ConfigurationNode()
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_message: str = "Please provide configuration:",
        default_fields: Optional[List[str]] = None
    ):
        """
        Initialize configuration node.

        Args:
            default_message: Default message to show user
            default_fields: Default configuration fields
        """
        self.node_name = "configuration"
        self.default_message = default_message
        self.default_fields = default_fields or []

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Request configuration from user.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with user configuration
        """
        logger.info("Requesting configuration from user")

        # Get configuration context
        config_context = state.get('config_context', {})
        config_fields = config_context.get('fields', self.default_fields)

        # Prepare configuration request
        config_request = {
            'message': self.default_message,
            'fields': config_fields,
            'defaults': config_context.get('defaults', {}),
            'config_type': 'user_configuration'
        }

        # Use interrupt() to pause and wait for user input
        user_config = interrupt(config_request)

        logger.info("Received configuration from user")

        return {
            'user_configuration': user_config,
            'configuration_provided': True,
            'configuration_timestamp': datetime.now(UTC).isoformat()
        }
