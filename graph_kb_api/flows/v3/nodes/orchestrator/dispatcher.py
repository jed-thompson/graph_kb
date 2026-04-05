"""
Dispatcher node for orchestrator subgraph.

Builds agent contexts and dispatches to agents — single dispatch dict
or parallel dispatch via Send() objects.
"""

from typing import Any, Dict, List

from langgraph.types import Send

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.utils.error_handling import handle_agent_exception

# Agent type → node name mapping (Requirement 3.2)
AGENT_TYPE_TO_NODE: Dict[str, str] = {
    "architect": "architect_agent",
    "lead_engineer": "engineer_agent",
    "doc_extractor": "doc_extractor_agent",
}


def agent_type_to_node(agent_type: str) -> str:
    """Map an agent type string to the corresponding LangGraph node name."""
    node = AGENT_TYPE_TO_NODE.get(agent_type)
    if node is None:
        raise ValueError(
            f"Unknown agent_type '{agent_type}'. "
            f"Valid types: {sorted(AGENT_TYPE_TO_NODE)}"
        )
    return node


class DispatcherNode(BaseWorkflowNodeV3):
    """
    Builds agent contexts and dispatches to agents.

    For each ready task:
    - Build agent_context with review feedback, clarification responses, summaries
    - Map agent type to node name
    - Create Send() for parallel dispatch OR single dispatch dict
    """

    def __init__(self):
        super().__init__("dispatcher")

    async def _execute_async(
        self, state: Dict[str, Any], services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Dispatch ready tasks to agents."""
        ready_tasks: List[Dict[str, Any]] = state.get("ready_tasks", [])
        task_contexts: Dict[str, Dict[str, Any]] = state.get("task_contexts", {})
        tool_assignments: Dict[str, List[str]] = state.get("tool_assignments", {})
        is_rework: bool = state.get("is_rework", False)
        rework_count: int = state.get("rework_count", 0)
        max_reworks: int = state.get("max_reworks", 3)
        review_feedback: str = state.get("review_feedback", "") or ""
        clarification_responses: Dict[str, Any] = state.get(
            "clarification_responses", {}
        )
        section_summaries: Dict[str, str] = state.get("section_summaries", {})
        progress_events: List[Dict[str, Any]] = state.get("progress_events", [])

        dispatches: List[tuple[Dict[str, Any], Dict[str, Any]]] = []

        for task in ready_tasks:
            task_id = task.get("task_id", "?")
            context = task_contexts.get(task_id, {})

            # Apply tool assignments
            if task_id in tool_assignments:
                task["tool_assignments"] = tool_assignments[task_id]

            # Build agent_context
            agent_context = dict(context)

            # Inject review feedback on rework (Requirements 5.1, 5.2)
            if is_rework and review_feedback:
                agent_context["review_feedback"] = review_feedback
                agent_context["rework_instructions"] = (
                    "Previous draft was rejected. Reviewer feedback:\n"
                    f"{review_feedback}\n"
                    "Please address all feedback points in your revised draft."
                )

            # Include clarification_responses (Requirement 14.3)
            if clarification_responses:
                agent_context["clarification_responses"] = dict(clarification_responses)

            # Include section_summaries, NOT full completed_sections (Requirement 3.3)
            agent_context["section_summaries"] = dict(section_summaries)

            dispatches.append((task, agent_context))

        # Single or parallel dispatch
        if len(dispatches) == 1:
            return self._single_dispatch(
                dispatches[0], is_rework, rework_count, max_reworks, progress_events
            )
        else:
            return self._parallel_dispatch(dispatches, rework_count, progress_events)

    def _single_dispatch(
        self,
        dispatch: tuple[Dict[str, Any], Dict[str, Any]],
        is_rework: bool,
        rework_count: int,
        max_reworks: int,
        progress_events: List[Dict[str, Any]],
    ) -> NodeExecutionResult:
        """Handle single task dispatch."""
        task, agent_ctx = dispatch
        try:
            node_name = agent_type_to_node(task.get("agent_type", "architect"))
        except ValueError as exc:
            self.logger.error("Dispatcher: %s", exc)
            return NodeExecutionResult.success(
                output={
                    **handle_agent_exception(exc, task, rework_count, max_reworks),
                    "progress_events": progress_events,
                    "route_to": "end",
                }
            )

        self.logger.info(
            f"Dispatcher: single dispatch → {node_name} "
            f"(task '{task.get('task_id', '?')}')"
        )
        new_rework_count = (rework_count + 1) if is_rework else 0
        return NodeExecutionResult.success(
            output={
                "current_task": task,
                "assigned_agent": task.get("agent_type", ""),
                "agent_context": agent_ctx,
                "rework_count": new_rework_count,
                "progress_events": progress_events,
                "route_to": "single",
            }
        )

    def _parallel_dispatch(
        self,
        dispatches: List[tuple[Dict[str, Any], Dict[str, Any]]],
        rework_count: int,
        progress_events: List[Dict[str, Any]],
    ) -> NodeExecutionResult:
        """Handle parallel dispatch via Send() API (Requirement 2.1)."""
        sends: List[Send] = []

        for task, agent_ctx in dispatches:
            try:
                node_name = agent_type_to_node(task.get("agent_type", "architect"))
            except ValueError as exc:
                self.logger.warning(
                    "Dispatcher: skipping task '%s' in parallel batch due to error: %s",
                    task.get("task_id", "?"),
                    exc,
                )
                continue

            self.logger.info(
                f"Dispatcher: parallel dispatch → {node_name} "
                f"(task '{task.get('task_id', '?')}')"
            )
            sends.append(
                Send(
                    node_name,
                    {
                        "current_task": task,
                        "assigned_agent": task.get("agent_type", ""),
                        "agent_context": agent_ctx,
                        "rework_count": 0,
                        "progress_events": progress_events,
                    },
                )
            )

        if not sends:
            self.logger.error("Dispatcher: all tasks in parallel batch failed")
            return NodeExecutionResult.success(
                output={
                    "review_verdict": "rework_needed",
                    "review_feedback": "All tasks in parallel batch failed.",
                    "progress_events": progress_events,
                    "route_to": "end",
                }
            )

        self.logger.info(f"Dispatcher: parallel dispatch with {len(sends)} Send(s)")
        return NodeExecutionResult.success(
            output={
                "sends": sends,
                "progress_events": progress_events,
                "route_to": "parallel",
            }
        )
