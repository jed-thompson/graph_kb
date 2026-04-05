"""
Task selector node for orchestrator subgraph.

Selects ready tasks from the TODO list based on parallel groups
and dependency satisfaction.
"""

from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3


class TaskSelectorNode(BaseWorkflowNodeV3):
    """
    Selects ready tasks from the TODO list.

    Determines which tasks can be dispatched now based on:
    - Current task index
    - Parallel group membership
    - Dependency satisfaction (completed_sections)
    - Rework mode (single task re-dispatch)
    """

    def __init__(self):
        super().__init__("task_selector")

    async def _execute_async(
        self, state: Dict[str, Any], services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Select ready tasks and determine routing."""
        todo_list: List[Dict[str, Any]] = state.get("todo_list", [])
        idx: int = state.get("current_task_index", 0)
        parallel_groups: List[List[str]] = state.get("parallel_groups", [])
        completed_sections: Dict[str, str] = state.get("completed_sections", {}) or {}
        is_rework: bool = state.get("is_rework", False)

        # Guard: no tasks left
        if idx >= len(todo_list):
            self.logger.info("TaskSelector: no more tasks to dispatch")
            return NodeExecutionResult.success(
                output={
                    "ready_tasks": [],
                    "route_to": "end",
                }
            )

        # Rework mode: re-dispatch current task only
        if is_rework:
            self.logger.info("TaskSelector: rework mode - selecting single task")
            return NodeExecutionResult.success(
                output={
                    "ready_tasks": [todo_list[idx]],
                    "route_to": "context_fetch",
                }
            )

        # Normal mode: find ready tasks from parallel group
        ready_tasks = self._get_ready_tasks(
            todo_list, idx, parallel_groups, completed_sections
        )

        if not ready_tasks:
            # Fallback to current task
            ready_tasks = [todo_list[idx]]

        self.logger.info(f"TaskSelector: selected {len(ready_tasks)} ready task(s)")
        return NodeExecutionResult.success(
            output={
                "ready_tasks": ready_tasks,
                "route_to": "context_fetch",
            }
        )

    def _get_ready_tasks(
        self,
        todo_list: List[Dict[str, Any]],
        current_index: int,
        parallel_groups: List[List[str]],
        completed_sections: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Return tasks ready to be dispatched based on parallel groups and dependencies."""
        if current_index >= len(todo_list):
            return []

        current_task = todo_list[current_index]
        current_task_id = current_task.get("task_id", "")
        completed = completed_sections or {}

        # Find the parallel group containing the current task
        for group in parallel_groups:
            if current_task_id in group:
                ready: List[Dict[str, Any]] = []
                for task in todo_list:
                    tid = task.get("task_id", "")
                    if tid not in group:
                        continue
                    if task.get("status") in ("complete", "in_progress", "in_review"):
                        continue
                    # Check all dependencies are satisfied
                    deps_met = all(
                        dep_id in completed
                        for dep_id in (task.get("dependencies") or [])
                    )
                    # Also accept task_ids whose section_id is in completed_sections
                    if not deps_met:
                        dep_section_ids = set()
                        for t in todo_list:
                            if t.get("task_id") in (task.get("dependencies") or []):
                                dep_section_ids.add(t.get("section_id", ""))
                        deps_met = all(
                            sid in completed for sid in dep_section_ids if sid
                        )
                    if deps_met:
                        ready.append(task)
                if ready:
                    return ready

        # Fallback: just the current task
        return [current_task]
