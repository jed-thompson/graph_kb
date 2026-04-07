"""
Result aggregation node for multi-agent workflow.

Merges and resolves agent outputs intelligently.
"""

import json
from typing import Any, Dict, List

from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ResultAggregationNode(BaseWorkflowNodeV3):
    """
    Merges agent outputs intelligently.

    Detects conflicts between agent outputs and uses LLM to resolve them.
    Produces a consolidated result with attribution.
    """

    def __init__(self):
        super().__init__("result_aggregation")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute result aggregation.

        Args:
            state: Current workflow state with agent_outputs
            services: Injected services

        Returns:
            NodeExecutionResult with aggregated results
        """
        try:
            self._setup_execution_context(state, services)

            agent_outputs = state.get('agent_outputs', {})

            if not agent_outputs:
                return NodeExecutionResult.success(
                    output={'aggregated_results': {}}
                )

            # Detect conflicts between agent outputs
            conflicts = self._detect_conflicts(agent_outputs)

            if conflicts:
                logger.info(
                    f"Detected {len(conflicts)} conflicts, attempting resolution"
                )
                # Use LLM to resolve conflicts
                resolutions = await self._resolve_conflicts(conflicts, services)
                aggregated = self._merge_outputs(agent_outputs, resolutions)
            else:
                logger.info("No conflicts detected, merging outputs directly")
                aggregated = self._merge_outputs(agent_outputs)

            # Build attribution summary
            attribution = self._build_attribution(agent_outputs, state)

            logger.info(
                "Result aggregation completed",
                data={
                    'agents_contributed': list(agent_outputs.keys()),
                    'conflicts_resolved': len(conflicts),
                }
            )

            return NodeExecutionResult.success(
                output={
                    'aggregated_results': aggregated,
                    'conflicts_resolved': len(conflicts) > 0,
                    'attribution': attribution
                }
            )

        except Exception as e:
            logger.error(
                f"Result aggregation failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Result aggregation failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    def _detect_conflicts(self, agent_outputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Detect conflicts between agent outputs.

        Args:
            agent_outputs: Dictionary of agent outputs

        Returns:
            List of conflict descriptions
        """
        conflicts = []

        # Find tasks with multiple agents working
        task_contributions = {}
        for task_id, output in agent_outputs.items():
            if task_id not in task_contributions:
                task_contributions[task_id] = []

        for task_id, output_list in task_contributions.items():
            task_contributions[task_id].append(output)

        # Check for tasks handled by multiple agents
        for task_id, contributions in task_contributions.items():
            if len(contributions) > 1:
                # Multiple agents worked on this task - potential conflict
                conflicts.append({
                    'task_id': task_id,
                    'conflict_type': 'multiple_agents',
                    'details': f"Multiple agents provided outputs: {len(contributions)}"
                })

        return conflicts

    async def _resolve_conflicts(
        self,
        conflicts: List[Dict[str, Any]],
        services: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Use LLM to resolve conflicts between agent outputs.

        Args:
            conflicts: List of conflict descriptions
            services: Injected services

        Returns:
            Dictionary of conflict resolutions
        """
        app_context = self._get_app_context(services)
        if not app_context:
            logger.error("App context not available for conflict resolution")
            return {}

        # Build conflict resolution prompt
        prompt = get_agent_prompt_manager().render_prompt(
            "result_aggregation",
            subdir="nodes",
            conflicts=self._format_conflicts(conflicts)
        )

        resolution = await app_context.llm.a_generate_response(prompt)

        try:
            resolution_data = json.loads(resolution)
            return resolution_data
        except json.JSONDecodeError:
            return {}

    def _format_conflicts(self, conflicts: List[Dict[str, Any]]) -> str:
        """Format conflicts for LLM prompt."""
        return "\n".join([
            f"Conflict {i+1}: Task {c.get('task_id')}, Details: {c.get('details')}"
            for i, c in enumerate(conflicts)
        ])

    def _merge_outputs(
        self,
        agent_outputs: Dict[str, Any],
        resolutions: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Merge agent outputs into consolidated results.

        Args:
            agent_outputs: Dictionary of agent outputs
            resolutions: Conflict resolutions (optional)

        Returns:
            Merged results dictionary
        """
        merged = {}

        for task_id, output in agent_outputs.items():
            # Check if there was a resolution for this task
            if resolutions:
                resolution = resolutions.get(task_id)
                if resolution:
                    # Use the resolved output
                    merged[task_id] = resolution
                    continue

            # Use the original output
            merged[task_id] = output

        return merged

    def _build_attribution(self, agent_outputs: Dict[str, Any], state: Dict[str, Any]) -> str:
        """
        Build attribution summary for merged results.

        Args:
            agent_outputs: Dictionary of agent outputs

        Returns:
            Attribution summary as formatted string
        """
        if not agent_outputs:
            return "No agent outputs to attribute"

        lines = ["## Agent Attribution", ""]

        for agent_type, output in agent_outputs.items():
            # Count tasks handled by this agent type
            tasks_handled = len([
                t for t in state.get('sub_tasks', [])
                if t.get('agent_assignments') and
                any(a.get('agent_type') == agent_type for a in t.get('agent_assignments', []))
            ])

            if tasks_handled == 0:
                continue

            lines.append(f"\n**{agent_type}**")
            lines.append(f"- Tasks handled: {tasks_handled}")
            lines.append(f"- Output: {output}")

        return "\n".join(lines)
