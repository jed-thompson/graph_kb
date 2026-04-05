"""
Quality check node for multi-agent workflow.

Validates agent outputs against acceptance criteria for each review stage.
"""

import json
from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class QualityCheckNode(BaseWorkflowNodeV3):
    """
    Validates output quality against acceptance criteria.

    Performs LLM-based evaluation for:
    - Completion: All sub-tasks addressed, dependencies satisfied
    - Quality: Clarity, completeness, accuracy scores
    - Security: No hardcoded secrets, no SQL injection, proper error handling
    """

    # Quality criteria for each stage
    QUALITY_CRITERIA = {
        'completion': [
            'all_sub_tasks_addressed',
            'no_internal_inconsistencies',
            'dependencies_satisfied',
        ],
        'quality': [
            'clarity_score_min_0_8',
            'completeness_score_min_0_8',
            'accuracy_score_min_0_7',
        ],
        'security': [
            'no_hardcoded_secrets',
            'no_sql_injection_patterns',
            'no_xss_vulnerabilities',
            'proper_error_handling',
        ],
    }

    def __init__(self):
        super().__init__("quality_check")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute quality check for current review stage.

        Args:
            state: Current workflow state with review_stage
            services: Injected services

        Returns:
            NodeExecutionResult with review result
        """
        try:
            self._setup_execution_context(state, services)

            review_stage = state.get('review_stage', 'none')

            if review_stage not in self.QUALITY_CRITERIA:
                logger.warning(f"Unknown review stage: {review_stage}")
                return NodeExecutionResult.success(
                    output={'review_pass': {'stage': review_stage, 'passed': True, 'feedback': 'Unknown stage'}}
                )

            criteria = self.QUALITY_CRITERIA.get(review_stage, [])

            # Get app context for LLM access
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available",
                    metadata={'node_type': self.node_name, 'error_type': 'service_unavailable'}
                )

            # Get outputs to validate
            agent_outputs = state.get('agent_outputs', {})
            sub_tasks = state.get('sub_tasks', [])

            # Build quality check prompt
            prompt = self._build_quality_prompt(review_stage, agent_outputs, sub_tasks, criteria)

            logger.info(f"Running quality check for stage: {review_stage}")

            # Invoke LLM for quality evaluation
            evaluation = await app_context.llm.a_generate_response(prompt)

            # Parse evaluation result
            result = self._parse_evaluation_response(evaluation)

            # Record review pass
            review_pass = {
                'stage': review_stage,
                'passed': result.get('passed', False),
                'criteria_results': result.get('criteria_results', {}),
                'feedback': result.get('feedback', '')
            }

            review_passes = state.get('review_passes', [])

            return NodeExecutionResult.success(
                output={
                    'review_pass': review_pass,
                    'review_passes': review_passes + [review_pass]
                }
            )

        except Exception as e:
            logger.error(
                f"Quality check failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Quality check failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    def _build_quality_prompt(
        self,
        stage: str,
        agent_outputs: Dict[str, Any],
        sub_tasks: List[Dict[str, Any]],
        criteria: List[str]
    ) -> str:
        """Build quality evaluation prompt for LLM."""
        agent_outputs_summary = self._summarize_agent_outputs(agent_outputs)

        prompt = f"""Evaluate the following outputs against criteria.

**Review Stage:** {stage.upper()}

**Agent Outputs:**
{agent_outputs_summary}

**Sub-Tasks:**
{self._format_sub_tasks(sub_tasks)}

**Criteria to Evaluate:**
{self._format_criteria(criteria)}

**Instructions:**
1. For each criterion, determine if it is met
2. Provide your assessment with a brief explanation
3. Rate overall quality: PASS if all criteria met, FAIL otherwise
4. Be thorough but concise

**Output Format (JSON):**
{{
    "passed": true/false,
    "criteria_results": {{"criterion_name": true/false, "explanation": "..."}},
    "feedback": "Overall assessment and suggestions"
}}"""
        return prompt

    def _format_sub_tasks(self, sub_tasks: List[Dict[str, Any]]) -> str:
        """Format sub-tasks for quality check prompt."""
        if not sub_tasks:
            return "No sub-tasks to evaluate"
        return "\n".join([
            f"- Task {i+1}: {task.get('description', 'N/A')} (Dependencies: {', '.join(task.get('dependencies', []))})"
            for i, task in enumerate(sub_tasks[:5])
        ])

    def _format_criteria(self, criteria: List[str]) -> str:
        """Format criteria list for quality check prompt."""
        return "\n".join([f"- {c}" for c in criteria])

    def _summarize_agent_outputs(self, agent_outputs: Dict[str, Any]) -> str:
        """Summarize agent outputs for quality check prompt."""
        if not agent_outputs:
            return "No agent outputs available"
        return "\n".join([
            f"- Agent {task_id}: {output.get('output', 'N/A')[:100]}..."
            for task_id, output in agent_outputs.items()
        ])

    def _parse_evaluation_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM evaluation response."""
        try:
            data = json.loads(response)
            return {
                'passed': data.get('passed', False),
                'criteria_results': data.get('criteria_results', {}),
                'feedback': data.get('feedback', 'Failed to parse response')
            }
        except json.JSONDecodeError:
            return {
                'passed': False,
                'criteria_results': {},
                'feedback': 'Failed to parse LLM response as JSON'
            }
