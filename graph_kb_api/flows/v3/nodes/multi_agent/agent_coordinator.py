"""
Agent coordinator node for multi-agent workflow.

Orchestrate parallel/sequential execution of agents based on task dependencies.
"""
from graph_kb_api.context import AppContext

import asyncio
from typing import Any, Dict, List, Set, cast

from graph_kb_api.flows.v3.agents import AgentResult, BaseAgent
from graph_kb_api.flows.v3.models.types import AgentTask
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.workflow_state import UnifiedSpecState

logger = EnhancedLogger(__name__)


class AgentCoordinatorNode(BaseWorkflowNodeV3):
    """
    Orchestrates parallel/sequential execution of agents.

    Tasks are grouped by dependencies and executed in parallel where possible.
    Independent tasks run simultaneously to optimize performance.
    """

    def __init__(self):
        super().__init__("agent_coordinator")
        self._messenger = None
        self.max_parallel_agents = 3  # Configurable limit for parallel execution

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Execute agent coordination.

        Args:
            state: Current workflow state with agent_assignments
            services: Injected services

        Returns:
            NodeExecutionResult with agent_outputs and token usage
        """
        try:
            self._setup_execution_context(state, services)

            assignments = state.get("agent_assignments", [])

            if not assignments:
                return NodeExecutionResult.success(
                    output={
                        "agent_outputs": {},
                        "agent_tokens_used": {},
                    }
                )

            logger.info(
                f"Coordinating {len(assignments)} agent assignments",
                data={"assignment_count": len(assignments)},
            )

            # Group by dependencies (run in parallel where possible)
            dependency_groups = self._group_by_dependencies(assignments)

            agent_outputs = {}
            tokens_used = {}

            # Execute each group
            for group in dependency_groups:
                # Limit parallel execution
                if len(group) > self.max_parallel_agents:
                    logger.warning(
                        f"Limiting parallel agents to {self.max_parallel_agents}",
                        data={
                            "group_size": len(group),
                            "limit": self.max_parallel_agents,
                        },
                    )
                    group = group[: self.max_parallel_agents]

                # Run agents in this group in parallel
                results = await asyncio.gather(*[self._run_agent(assignment, services) for assignment in group])

                # Collect outputs and tokens
                for assignment, result in zip(group, results):
                    task_id = assignment.get("task_id", "unknown")
                    agent_type = assignment.get("agent_type", "unknown")

                    if result.get("error"):
                        logger.error(
                            f"Agent {agent_type} failed for task {task_id}",
                            data={"error": result["error"]},
                        )
                        continue

                    output = result.get("output", {})
                    agent_outputs[task_id] = output.get("output", "")
                    agent_tokens = output.get("tokens", 0)

                    # Track tokens per agent type
                    if agent_type not in tokens_used:
                        tokens_used[agent_type] = 0
                    tokens_used[agent_type] += agent_tokens

            logger.info(
                "Agent coordination completed",
                data={
                    "tasks_completed": len(agent_outputs),
                    "agents_used": list(tokens_used.keys()),
                },
            )

            return NodeExecutionResult.success(
                output={
                    "agent_outputs": agent_outputs,
                    "agent_tokens_used": tokens_used,
                }
            )

        except Exception as e:
            logger.error(
                f"Agent coordination failed: {e}",
                data={"node_type": self.node_name, "error_type": type(e).__name__},
            )
            return NodeExecutionResult.failure(
                f"Agent coordination failed: {str(e)}",
                metadata={"node_type": self.node_name, "error_type": type(e).__name__},
            )

    def _group_by_dependencies(self, assignments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Group tasks by dependencies.

        Tasks with no dependencies run in parallel.
        Tasks with dependencies run after their prerequisites complete.

        Args:
            assignments: List of agent assignments with dependencies field

        Returns:
            List of groups, where each group can run in parallel
        """
        task_map = {a.get("task_id", ""): a for a in assignments}
        completed = set()

        groups = []
        current_group = []

        # Process tasks in order
        for assignment in assignments:
            task_id = assignment.get("task_id", "")
            dependencies = assignment.get("dependencies", [])

            # Check if all dependencies are satisfied
            ready = all(dep in completed for dep in dependencies)

            if ready:
                current_group.append(assignment)
                completed.add(task_id)
                # If this task enables others, check if we should start a new group
                self._check_and_start_new_groups(assignment, task_map, completed, groups, current_group)
            else:
                # Task has unmet dependencies, save for later
                groups.append(current_group)
                current_group = [assignment]
                completed.add(task_id)

        # Add final group if there are any remaining
        if current_group:
            groups.append(current_group)

        return groups

    def _check_and_start_new_groups(
        self,
        assignment: Dict[str, Any],
        task_map: Dict[str, Dict[str, Any]],
        completed: Set[str],
        groups: List[List[Dict[str, Any]]],
        current_group: List[Dict[str, Any]],
    ) -> None:
        """
        Check if any unblocked tasks can now run and start new groups.
        """
        dependencies = assignment.get("dependencies", [])

        for dep_id in dependencies:
            if dep_id not in completed:
                # Find assignment for this dependency
                dep_assignment = task_map.get(dep_id)
                if dep_assignment and not any(dep_assignment in g for g in groups):
                    # This dependency is now complete, add its group
                    new_group = [dep_assignment]
                    # Check if this enables other tasks in current_group
                    ready_tasks = []
                    remaining_tasks = []

                    for task in current_group:
                        task_deps = task.get("dependencies", [])
                        if all(d in completed for d in task_deps):
                            ready_tasks.append(task)
                        else:
                            remaining_tasks.append(task)

                    if ready_tasks:
                        # Start new group with these ready tasks
                        groups.append(ready_tasks)
                        # Update current_group to remaining
                        current_group = remaining_tasks
                    else:
                        # All tasks in current_group still blocked
                        # Update current_group
                        current_group = remaining_tasks

                    groups.append(new_group)
                    completed.add(dep_id)
                    return

    async def _run_agent(self, assignment: Dict[str, Any], services: ServiceRegistry) -> AgentResult:
        """
        Run a single agent using the agent registry.

        Args:
            assignment: Assignment dict containing agent_type and task
            services: Injected services

        Returns:
            AgentResult with output, tokens, and optional error
        """
        try:
            agent_type = assignment.get("agent_type", "unknown")

            # Import here to avoid circular dependency
            from graph_kb_api.flows.v3.agents.registry import AgentRegistry

            agent: BaseAgent | None = AgentRegistry.get_agent(agent_type)

            if not agent:
                return AgentResult(
                    output=f"No agent found for type: {agent_type}",
                    tokens=0,
                    error=f"Unknown agent type: {agent_type}",
                )

            task: AgentTask = {
                "description": assignment.get("description", ""),
                "task_id": assignment.get("task_id", ""),
            }

            state = {**services.get("state", {}), "task": task}
            app_context: AppContext | None = services.get("app_context")

            # Execute agent — coordinator provides a minimal state subset and
            # AppContext instead of WorkflowContext; casts needed until the
            # coordinator is refactored to construct a proper WorkflowContext.
            result: AgentResult = await agent.execute(
                task, cast(UnifiedSpecState, state), cast(WorkflowContext | None, app_context)
            )

            return result

        except Exception as e:
            logger.error(f"Agent execution failed for {agent_type}: {e}", exc_info=True)
            return {
                "output": f"Execution error: {str(e)}",
                "tokens": 0,
                "error": str(e),
            }
