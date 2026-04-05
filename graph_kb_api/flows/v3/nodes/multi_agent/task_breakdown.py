"""
Task breakdown node for multi-agent workflow.

Breaks complex tasks into sub-tasks using LLM,
creating a structured task graph for agent coordination.
"""

import json
from typing import Any, Dict

from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class TaskBreakdownNode(BaseWorkflowNodeV3):
    """
    Breaks complex tasks into sub-tasks using LLM.

    Uses LLM to decompose user requests into manageable sub-tasks
    with identified dependencies and priorities.
    """

    # System prompt for task breakdown
    SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("task_breakdown", subdir="nodes")

    MAX_SUB_TASKS = 7  # Limit to prevent excessive breakdown

    def __init__(self):
        super().__init__("task_breakdown")
        self._messenger = None

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """Execute task breakdown."""
        try:
            self._setup_execution_context(state, services)

            user_input = state.get("user_input", "")

            if not user_input:
                return NodeExecutionResult.failure(
                    "No user input available for breakdown",
                    metadata={"node_type": self.node_name, "error_type": "validation"},
                )

            # Get app context for LLM access
            app_context = self._get_app_context(services)
            if not app_context:
                return NodeExecutionResult.failure(
                    "Application context not available",
                    metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
                )

            # Use LLM to break down task
            logger.info("Requesting task breakdown from LLM", data={"input_length": len(user_input)})

            breakdown_response = await app_context.llm.a_generate_response(self.SYSTEM_PROMPT, user_input)

            # Parse JSON response with error handling
            try:
                breakdown_data = json.loads(breakdown_response)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse breakdown JSON: {e}")
                # Create fallback simple breakdown
                breakdown_data = self._create_fallback_breakdown(user_input)

            # Extract and validate breakdown
            primary_task = breakdown_data.get("primary_task", {})
            sub_tasks = breakdown_data.get("sub_tasks", [])

            # Validate sub-tasks structure
            validated_tasks = []
            for i, task in enumerate(sub_tasks[: self.MAX_SUB_TASKS]):
                if self._validate_task(task, i):
                    validated_tasks.append(task)
                else:
                    logger.warning(f"Skipping invalid task {i}: {task}")

            if not validated_tasks:
                return NodeExecutionResult.failure(
                    "No valid sub-tasks generated from breakdown",
                    metadata={"node_type": self.node_name, "error_type": "validation"},
                )

            logger.info(
                "Task breakdown completed",
                data={
                    "sub_tasks_count": len(validated_tasks),
                    "primary_task_keys": list(primary_task.keys()) if primary_task else 0,
                },
            )

            return NodeExecutionResult.success(
                output={
                    "primary_task": primary_task,
                    "sub_tasks": validated_tasks,
                }
            )

        except Exception as e:
            logger.error(
                f"Task breakdown failed: {e}", data={"node_type": self.node_name, "error_type": type(e).__name__}
            )
            return NodeExecutionResult.failure(
                f"Task breakdown failed: {str(e)}",
                metadata={"node_type": self.node_name, "error_type": type(e).__name__},
            )

    def _create_fallback_breakdown(self, user_input: str) -> Dict[str, Any]:
        """Create a simple fallback breakdown if LLM fails."""
        words = user_input.split()
        if len(words) == 0:
            return {
                "primary_task": {"objective": user_input, "context": ""},
                "sub_tasks": [
                    {
                        "id": "task_1",
                        "description": user_input,
                        "dependencies": [],
                        "priority": "medium",
                        "estimated_complexity": "medium",
                    }
                ],
            }
        return {
            "primary_task": {"objective": " ".join(words), "context": ""},
            "sub_tasks": [
                {
                    "id": f"task_{i}",
                    "description": word,
                    "dependencies": [],
                    "priority": "low",
                    "estimated_complexity": "simple",
                }
                for i, word in enumerate(words)
            ],
        }

    def _validate_task(self, task: Dict[str, Any], index: int) -> bool:
        """Validate a task has required fields."""
        required_fields = ["id", "description", "priority", "estimated_complexity"]
        return all(field in task for field in required_fields)
