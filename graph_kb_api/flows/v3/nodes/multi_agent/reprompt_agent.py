"""
Reprompt agent node for multi-agent workflow.

Handles reprompting agents when quality checks fail or feedback is provided.
"""

import json
from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class RePromptAgent(BaseWorkflowNodeV3):
    """
    Reprompts agents based on review feedback.

    When quality check fails or review provides feedback, this node:
    - Extracts relevant feedback
    - Updates agent tasks with improvement guidance
    - Increments reprompt counter
    - Enforces max_reprompts limit
    """

    def __init__(self):
        super().__init__("reprompt_agent")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute agent reprompting.

        Args:
            state: Current workflow state with review failures
            services: Injected services

        Returns:
            NodeExecutionResult with updated tasks and reprompt count
        """
        try:
            self._setup_execution_context(state, services)

            reprompt_attempts = state.get('reprompt_attempts', 0)
            max_reprompts = state.get('max_reprompts', 3)

            # Check if we've exceeded reprompt limit
            if reprompt_attempts >= max_reprompts:
                logger.warning(
                    f"Max reprompts ({max_reprompts}) reached, proceeding with current results"
                )
                return NodeExecutionResult.success(
                    output={
                        'reprompt_complete': False,
                        'reason': 'max_reprompts_exceeded',
                        'reprompt_attempts': reprompt_attempts
                    }
                )

            # Get review failures to address
            review_failures = state.get('review_failures', [])
            review_passes = state.get('review_passes', [])

            # Get most recent review feedback
            feedback = self._extract_feedback(review_failures, review_passes)

            if not feedback:
                logger.warning("No feedback found for reprompting")
                return NodeExecutionResult.success(
                    output={
                        'reprompt_complete': False,
                        'reason': 'no_feedback',
                        'reprompt_attempts': reprompt_attempts
                    }
                )

            # Get app context for LLM access
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available",
                    metadata={'node_type': self.node_name, 'error_type': 'service_unavailable'}
                )

            # Get sub-tasks to update
            sub_tasks = state.get('sub_tasks', [])
            agent_outputs = state.get('agent_outputs', {})

            logger.info(
                f"Reprompting agents (attempt {reprompt_attempts + 1}/{max_reprompts})",
                data={'feedback_count': len(feedback)}
            )

            # Generate improved task descriptions with feedback
            updated_tasks = await self._generate_task_updates(
                sub_tasks,
                agent_outputs,
                feedback,
                app_context
            )

            # Record reprompt
            reprompt_record = {
                'attempt': reprompt_attempts + 1,
                'feedback': feedback,
                'stage': state.get('review_stage', 'none')
            }

            return NodeExecutionResult.success(
                output={
                    'sub_tasks': updated_tasks,
                    'reprompt_attempts': reprompt_attempts + 1,
                    'reprompt_complete': True,
                    'reprompt_record': reprompt_record
                }
            )

        except Exception as e:
            logger.error(
                f"Reprompt agent failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Reprompt agent failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    def _extract_feedback(
        self,
        review_failures: List[Dict[str, Any]],
        review_passes: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Extract feedback from review results.

        Args:
            review_failures: List of failed review attempts
            review_passes: List of review passes with feedback

        Returns:
            List of feedback strings
        """
        feedback = []

        # Extract from failures
        for failure in review_failures[-3:]:  # Only last 3 failures
            if 'feedback' in failure:
                feedback.append(f"Failure feedback: {failure['feedback']}")

        # Extract from passes (even passed reviews may have suggestions)
        for review_pass in review_passes[-3:]:
            if 'feedback' in review_pass:
                feedback.append(f"Review feedback: {review_pass['feedback']}")

        # Extract criteria results from passes
        for review_pass in review_passes[-3:]:
            criteria_results = review_pass.get('criteria_results', {})
            for criterion, result in criteria_results.items():
                if not result:
                    # Criterion failed - add as feedback
                    explanation = result.get('explanation', criterion)
                    feedback.append(f"Failed criterion '{criterion}': {explanation}")

        return feedback

    async def _generate_task_updates(
        self,
        sub_tasks: List[Dict[str, Any]],
        agent_outputs: Dict[str, Any],
        feedback: List[str],
        app_context: Any
    ) -> List[Dict[str, Any]]:
        """
        Generate improved task descriptions based on feedback.

        Args:
            sub_tasks: Original sub-task descriptions
            agent_outputs: Current agent outputs
            feedback: Review feedback to address
            app_context: Application context with LLM

        Returns:
            Updated sub-task descriptions
        """
        # Build prompt for task improvement
        prompt = self._build_improvement_prompt(sub_tasks, agent_outputs, feedback)

        # Get improved tasks from LLM
        improved_tasks_text = await app_context.llm.a_generate_response(prompt)

        # Parse response
        improved_tasks = self._parse_improved_tasks(improved_tasks_text, sub_tasks)

        return improved_tasks

    def _build_improvement_prompt(
        self,
        sub_tasks: List[Dict[str, Any]],
        agent_outputs: Dict[str, Any],
        feedback: List[str]
    ) -> str:
        """Build task improvement prompt for LLM."""
        tasks_summary = "\n".join([
            f"- Task {i+1}: {task.get('description', 'N/A')}"
            for i, task in enumerate(sub_tasks)
        ])

        outputs_summary = "\n".join([
            f"- {agent}: {str(output)}"
            for agent, output in agent_outputs.items()
        ])

        feedback_summary = "\n".join([
            f"- {f}"
            for f in feedback
        ])

        prompt = f"""The following tasks were executed but failed quality review:

**Original Tasks:**
{tasks_summary}

**Agent Outputs:**
{outputs_summary}

**Review Feedback:**
{feedback_summary}

**Instructions:**
1. Analyze the feedback and identify specific improvements needed
2. For each task, provide an updated description that addresses the feedback
3. Keep the original task ID and dependencies
4. Add a 'improvement_notes' field to each task summarizing changes

**Output Format (JSON list):**
[
    {{
        "task_id": "task_1",
        "description": "Updated task description with improvements",
        "improvement_notes": "Summary of changes based on feedback",
        "dependencies": [...],
        "agent_type": "...",
        "priority": "..."
    }},
    ...
]

Return only valid JSON."""

        return prompt

    def _parse_improved_tasks(
        self,
        improved_tasks_text: str,
        original_tasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Parse improved tasks from LLM response.

        Args:
            improved_tasks_text: LLM response with improved tasks
            original_tasks: Original task list for fallback

        Returns:
            List of improved task dictionaries
        """
        try:
            improved_tasks = json.loads(improved_tasks_text)

            # Merge with original tasks to preserve fields not updated
            task_map = {task.get('task_id'): task for task in original_tasks}

            for improved in improved_tasks:
                task_id = improved.get('task_id')
                if task_id in task_map:
                    # Merge fields, keeping original unchanged fields
                    original = task_map[task_id]
                    original.update(improved)
                    task_map[task_id] = original

            return list(task_map.values())

        except json.JSONDecodeError:
            logger.warning("Failed to parse improved tasks, using originals")
            return original_tasks
