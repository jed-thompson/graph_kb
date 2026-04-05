"""
Task classifier node for multi-agent workflow.

Classifies sub-tasks to appropriate agent types using LLM,
enabling dynamic agent assignment based on task requirements.
"""

import json
from typing import Any, Dict

from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class TaskClassifierNode(BaseWorkflowNodeV3):
    """
    Classifies sub-tasks to appropriate agent types.

    Uses LLM to analyze each sub-task and determine which
    specialized agent is best suited to handle it.
    """

    # Available agent types
    AGENT_TYPES = {
        "code_analyst": "Code analysis, pattern finding, dependency tracing",
        "code_generator": "Writing, refactoring, generating code",
        "researcher": "Research, documentation, knowledge synthesis",
        "architect": "Design evaluation, architecture analysis",
        "security": "Security analysis, vulnerability detection",
    }

    # System prompt for classification
    CLASSIFIER_PROMPT = get_agent_prompt_manager().render_prompt(
        "task_classifier",
        subdir="nodes",
        agent_types=json.dumps(AGENT_TYPES, indent=2)
    )

    def __init__(self):
        super().__init__("task_classifier")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Execute task classification."""
        try:
            self._setup_execution_context(state, services)

            sub_tasks = state.get('sub_tasks', [])

            if not sub_tasks:
                return NodeExecutionResult.error(
                    "No sub-tasks available for classification",
                    metadata={'node_type': self.node_name, 'error_type': 'validation'}
                )

            # Get app context for LLM access
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available",
                    metadata={'node_type': self.node_name, 'error_type': 'service_unavailable'}
                )

            # Classify each sub-task
            classifications = []
            for task in sub_tasks:
                classification = await self._classify_single_task(task, app_context)
                classifications.append(classification)

            logger.info(
                "Task classification completed",
                data={
                    'tasks_classified': len(classifications),
                    'agent_types': [c.get('agent_type') for c in classifications]
                }
            )

            return NodeExecutionResult.success(
                output={
                    'agent_assignments': classifications,
                }
            )

        except Exception as e:
            logger.error(
                f"Task classification failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Task classification failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    async def _classify_single_task(
        self,
        task: Dict[str, Any],
        app_context: Any
    ) -> Dict[str, Any]:
        """Classify a single task using LLM."""
        task_id = task.get('id', 'unknown')
        description = task.get('description', '')

        # Create classification prompt
        prompt = f"{self.CLASSIFIER_PROMPT}\n\nTask ID: {task_id}\nDescription: {description}"

        response = await app_context.llm.a_generate_response(prompt)

        # Parse response with fallback
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            # Fallback to simple keyword matching
            result = self._fallback_classify(description)

        return {
            'task_id': task_id,
            **result
        }

    def _fallback_classify(self, description: str) -> Dict[str, Any]:
        """Simple keyword-based fallback classification."""
        description_lower = description.lower()

        # Keyword matching for each agent type
        agent_keywords = {
            "code_analyst": ["analyze", "pattern", "dependency", "structure", "tracing"],
            "code_generator": ["write", "create", "generate", "refactor", "implement"],
            "researcher": ["document", "explain", "research", "understand", "investigate"],
            "architect": ["design", "architecture", "structure", "evaluate"],
            "security": ["security", "vulnerability", "safe", "audit"],
        }

        # Find best matching agent type
        best_match = "code_analyst"  # Default
        best_score = 0

        for agent_type, keywords in agent_keywords.items():
            score = sum(1 for kw in keywords if kw in description_lower)
            if score > best_score:
                best_score = score
                best_match = agent_type

        return {
            'task_id': 'unknown',
            'agent_type': best_match,
            'confidence': 'Low',  # Low confidence for fallback
            'reasoning': f"Matched based on {best_score} keywords: {best_match}"
        }

    def _extract_agent_type(self, response: str) -> str:
        """Extract agent type from classification response."""
        try:
            data = json.loads(response)
            return data.get('agent_type', 'code_analyst')
        except json.JSONDecodeError:
            return 'code_analyst'  # Default fallback

    def _extract_confidence(self, response: str) -> str:
        """Extract confidence level from classification response."""
        try:
            data = json.loads(response)
            return data.get('confidence', 'Medium')
        except json.JSONDecodeError:
            return 'Medium'  # Default fallback
