"""
Tool selector node for multi-agent workflow.

Dynamically assigns tools to agents based on task context
and agent capabilities.
"""

from typing import Any, Dict

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.tools.tool_assigner import ToolAssigner
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ToolSelectorNode(BaseWorkflowNodeV3):
    """
    Dynamically assigns tools based on task context and agent capabilities.

    Uses the ToolAssigner to match agent requirements with available tools.
    """

    def __init__(self):
        super().__init__("tool_selector")
        self._messenger = None
        self.tool_assigner = None  # Will be initialized with tools from services

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute tool selection for all agent assignments.

        Args:
            state: Current workflow state with agent_assignments
            services: Injected services

        Returns:
            NodeExecutionResult with tool_assignments for each task
        """
        try:
            self._setup_execution_context(state, services)

            # Get or create tool assigner
            if self.tool_assigner is None:
                all_tools = services.get('available_tools', [])
                self.tool_assigner = ToolAssigner(all_tools)
                services['tool_assigner'] = self.tool_assigner

            assignments = state.get('agent_assignments', [])
            all_tasks = state.get('sub_tasks', [])

            if not assignments:
                return NodeExecutionResult.success(
                    output={'tool_assignments': {}}
                )

            # Create tool assignments for each task
            tool_assignments = {}
            agent_tools_used = set()

            for assignment in assignments:
                task_id = assignment.get('task_id', 'unknown')
                agent_type = assignment.get('agent_type', 'unknown')

                # Get task details
                task = next((t for t in all_tasks if t.get('id') == task_id), {})

                # Assign tools based on agent type
                assigned_tools = self.tool_assigner.assign_tools(task, agent_type)

                # Track which tools were used
                for tool in assigned_tools:
                    agent_tools_used.add(tool.name)

                tool_assignments[task_id] = {
                    'agent_type': agent_type,
                    'tools': [t.name for t in assigned_tools]
                }

            logger.info(
                "Tool selection completed",
                data={
                    'tasks_processed': len(tool_assignments),
                    'unique_tools_used': len(agent_tools_used),
                }
            )

            return NodeExecutionResult.success(
                output={'tool_assignments': tool_assignments}
            )

        except Exception as e:
            logger.error(
                f"Tool selection failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Tool selection failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
