"""
Clarification node for multi-agent workflow.

Handles human-in-the-loop clarification when user input is ambiguous.
"""

from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ClarificationNode(BaseWorkflowNodeV3):
    """
    Handles clarification when user input is ambiguous.

    This node:
    - Identifies ambiguous aspects of user input
    - Generates clarification questions
    - Awaits user responses
    - Merges responses into context
    """

    def __init__(self):
        super().__init__("clarification")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute clarification process.

        Args:
            state: Current workflow state
            services: Injected services

        Returns:
            NodeExecutionResult with clarification questions or continuation flag
        """
        try:
            self._setup_execution_context(state, services)

            # Check if clarification questions already exist
            existing_questions = state.get('clarification_questions', [])
            if existing_questions:
                # Questions already generated, awaiting responses
                logger.info("Clarification questions exist, awaiting responses")
                return NodeExecutionResult.success(
                    output={
                        'awaiting_clarification': True,
                        'clarification_questions': existing_questions
                    }
                )

            # Get app context for LLM access
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available",
                    metadata={'node_type': self.node_name, 'error_type': 'service_unavailable'}
                )

            # Get user input to analyze
            user_input = state.get('user_input', '')
            template_id = state.get('template_id')
            template_vars = state.get('template_vars', {})

            logger.info("Generating clarification questions")

            # Generate clarification questions
            clarification_questions = await self._generate_clarification_questions(
                user_input,
                template_id,
                template_vars,
                app_context
            )

            # Check if any questions were generated
            if not clarification_questions:
                # No ambiguity detected, proceed with task breakdown
                logger.info("No ambiguity detected, proceeding without clarification")
                return NodeExecutionResult.success(
                    output={
                        'awaiting_clarification': False,
                        'clarification_questions': [],
                        'clarification_needed': False
                    }
                )

            # Clarification questions generated, mark as awaiting
            return NodeExecutionResult.success(
                output={
                    'awaiting_clarification': True,
                    'clarification_questions': clarification_questions,
                    'clarification_needed': True
                }
            )

        except Exception as e:
            logger.error(
                f"Clarification node failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Clarification failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    async def _generate_clarification_questions(
        self,
        user_input: str,
        template_id: str,
        template_vars: Dict[str, Any],
        app_context: Any
    ) -> List[str]:
        """
        Generate clarification questions using LLM.

        Args:
            user_input: Original user input
            template_id: Template ID if used
            template_vars: Template variables
            app_context: Application context with LLM

        Returns:
            List of clarification questions
        """
        # Build prompt for clarification question generation
        prompt = self._build_clarification_prompt(user_input, template_id, template_vars)

        # Get questions from LLM
        response = await app_context.llm.a_generate_response(prompt)

        # Parse response
        questions = self._parse_clarification_response(response)

        return questions

    def _build_clarification_prompt(
        self,
        user_input: str,
        template_id: str,
        template_vars: Dict[str, Any]
    ) -> str:
        """Build clarification prompt for LLM."""
        template_info = ""
        if template_id:
            template_info = f"\n\n**Template Used:** {template_id}"
            if template_vars:
                template_info += f"\n**Template Variables:** {template_vars}"

        prompt = f"""The following user input may contain ambiguities:

**User Input:**
{user_input}
{template_info}

**Instructions:**
1. Analyze the input for ambiguous terms, missing context, or unclear requirements
2. Generate clarifying questions to resolve these ambiguities
3. Focus on aspects that would affect task execution quality
4. Ask at most 5 questions
5. If the input is clear and specific, return an empty list

**Output Format (JSON list):**
[
    "Question 1 text?",
    "Question 2 text?",
    ...
]

Return only valid JSON with a list of strings."""

        return prompt

    def _parse_clarification_response(self, response: str) -> List[str]:
        """
        Parse clarification questions from LLM response.

        Args:
            response: LLM response with questions

        Returns:
            List of clarification question strings
        """
        import json

        try:
            questions = json.loads(response)
            if isinstance(questions, list):
                return [str(q) for q in questions if q]
            return []
        except json.JSONDecodeError:
            logger.warning("Failed to parse clarification response")
            return []

    async def process_clarification_responses(
        self,
        state: Dict[str, Any],
        responses: List[str]
    ) -> NodeExecutionResult:
        """
        Process user responses to clarification questions.

        Args:
            state: Current workflow state
            responses: User responses to clarification questions

        Returns:
            NodeExecutionResult with updated context and continuation flag
        """
        try:
            # Get app context for LLM access
            services = {}  # Extract from state context if needed
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available",
                    metadata={'node_type': self.node_name, 'error_type': 'service_unavailable'}
                )

            # Get original input and questions
            user_input = state.get('user_input', '')
            questions = state.get('clarification_questions', [])

            # Build enhanced context
            enhanced_context = await self._integrate_clarifications(
                user_input,
                questions,
                responses,
                app_context
            )

            logger.info(f"Processed {len(responses)} clarification responses")

            return NodeExecutionResult.success(
                output={
                    'awaiting_clarification': False,
                    'clarification_responses': responses,
                    'enhanced_user_input': enhanced_context,
                    'clarification_complete': True
                }
            )

        except Exception as e:
            logger.error(
                f"Processing clarification responses failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Failed to process clarification: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    async def _integrate_clarifications(
        self,
        user_input: str,
        questions: List[str],
        responses: List[str],
        app_context: Any
    ) -> str:
        """
        Integrate clarification responses into enhanced user input.

        Args:
            user_input: Original user input
            questions: Clarification questions asked
            responses: User responses
            app_context: Application context with LLM

        Returns:
            Enhanced user input string
        """
        # Build context integration prompt
        prompt = self._build_integration_prompt(user_input, questions, responses)

        # Get integrated context from LLM
        enhanced = await app_context.llm.a_generate_response(prompt)

        return enhanced

    def _build_integration_prompt(
        self,
        user_input: str,
        questions: List[str],
        responses: List[str]
    ) -> str:
        """Build integration prompt for LLM."""
        qa_pairs = "\n".join([
            f"Q{i+1}: {q}\nA{i+1}: {responses[i] if i < len(responses) else 'No response'}"
            for i, q in enumerate(questions)
        ])

        prompt = f"""Integrate the following clarification responses into the original user input:

**Original Input:**
{user_input}

**Clarification Q&A:**
{qa_pairs}

**Instructions:**
1. Combine the original input with the clarification responses
2. Produce a clear, enhanced version of the user's request
3. Preserve the original intent while adding clarity from responses
4. Do not add the Q&A format in the output, just the integrated request

**Output:**
The enhanced user input as a single clear paragraph or statement."""

        return prompt
