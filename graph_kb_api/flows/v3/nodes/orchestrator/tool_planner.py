"""
Tool planner node for orchestrator subgraph.

Plans or replans tools for each ready task based on rework state
and clarification responses.
"""

from typing import Any, Dict, List

from graph_kb_api.flows.v3.agents.tool_planner_agent import ToolPlannerAgent
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3


class ToolPlannerNode(BaseWorkflowNodeV3):
    """
    Plans or replans tools for each ready task.

    For each task:
    - On rework or after clarification: call ToolPlannerAgent.replan()
    - First-time dispatch: call ToolPlannerAgent.execute()
    """

    def __init__(self):
        super().__init__("tool_planner")
        self._tool_planner = ToolPlannerAgent()

    async def _execute_async(
        self, state: Dict[str, Any], services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Plan tools for all ready tasks."""
        ready_tasks: List[Dict[str, Any]] = state.get("ready_tasks", [])
        is_rework: bool = state.get("is_rework", False)
        _cr = state.get("clarification_responses", {})
        clarification_responses: Dict[str, Any] = _cr if isinstance(_cr, dict) else {}
        review_feedback: str = state.get("review_feedback", "") or ""
        tool_assignments: Dict[str, List[str]] = {}

        for task in ready_tasks:
            task_id = task.get("task_id", "?")

            try:
                if is_rework or clarification_responses:
                    # Replan on rework or clarification (Requirements 8.2, 8.3)
                    tool_plan = await self._tool_planner.replan(
                        task=task,
                        rework_feedback=review_feedback,
                        state=dict(state),
                    )
                    tool_assignments[task_id] = tool_plan.get("tool_assignments", [])
                else:
                    # First-time dispatch — plan tools (Requirement 8.1)
                    tool_result = await self._tool_planner.execute(
                        task=task, state=dict(state), app_context=None
                    )
                    assignments = tool_result.get("task_tool_assignments", {})
                    if task_id in assignments:
                        tool_assignments[task_id] = assignments[task_id]
            except Exception as exc:
                # Tool planning failure — non-fatal, proceed with existing
                self.logger.warning(
                    "ToolPlanner: tool planning failed for task '%s': %s",
                    task_id,
                    exc,
                )
                tool_assignments[task_id] = task.get("tool_assignments", [])

        self.logger.info(
            f"ToolPlanner: planned tools for {len(tool_assignments)} task(s)"
        )
        return NodeExecutionResult.success(
            output={
                "tool_assignments": tool_assignments,
                "route_to": "dispatcher",
            }
        )
