"""
Input prepare node for multi-agent workflow.

Parses and prepares user input for multi-agent processing,
including template detection and clarification triggering.
"""

import re
from typing import Any, Dict

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class InputPrepareNode(BaseWorkflowNodeV3):
    """
    Parses and prepares user input for multi-agent processing.

    Handles:
    - Parsing user query from command arguments
    - Detecting template syntax (e.g., "use template: refactor")
    - Basic validation for question clarity
    - Setting awaiting_clarification flag for vague inputs
    """

    # Regex for template detection: "use template: <name>"
    TEMPLATE_PATTERN = re.compile(r'use template:\s*(\w+)', re.IGNORECASE)

    def __init__(self):
        super().__init__("input_prepare")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Execute input preparation."""
        try:
            self._setup_execution_context(state, services)

            # Extract user query from args
            args = state.get('args', [])
            user_input = " ".join(args) if args else ""

            if not user_input:
                return NodeExecutionResult.error(
                    "No user input provided",
                    metadata={'node_type': self.node_name, 'error_type': 'validation'}
                )

            # Check for template syntax
            template_match = self.TEMPLATE_PATTERN.search(user_input)
            template_id = None
            awaiting_clarification = False
            clarification_questions = None
            template_vars = None

            if template_match:
                template_id = template_match.group(1)
                awaiting_clarification = True
                clarification_questions = [
                    "What variables should I use for this template?",
                    "Are there any specific requirements?"
                ]
                logger.info(
                    f"Template detected: {template_id}",
                    data={'template_id': template_id}
                )
            # Basic validation for vagueness (simple heuristic)
            elif len(user_input.split()) < 5:
                awaiting_clarification = True
                clarification_questions = [
                    "Can you be more specific about what you want?",
                    "Which part of the codebase should I focus on?",
                    "What specific function or feature are you asking about?",
                ]
                logger.info(
                    "Input marked for clarification",
                    data={'input_length': len(user_input)}
                )
            else:
                logger.info(
                    "Input processed successfully",
                    data={'input_length': len(user_input)}
                )

            return NodeExecutionResult.success(
                output={
                    'user_input': user_input,
                    'template_id': template_id,
                    'template_vars': template_vars,
                    'awaiting_clarification': awaiting_clarification,
                    'clarification_questions': clarification_questions,
                }
            )

        except Exception as e:
            logger.error(
                f"Input preparation failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Input preparation failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
