"""
Tool planner agent for the multi-agent feature spec workflow.

Deterministically assigns tools to agents based on task context requirements
and agent capabilities. Re-invocable per task — not just a one-shot upfront
pass — since tool needs can change after rework or human clarification.
"""

from typing import Any, Dict, List, Literal, cast

from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import (
    AgentResult,
    AgentTask,
    architect_capability,
    consistency_checker_capability,
    doc_extractor_capability,
    lead_engineer_capability,
    reviewer_critic_capability,
    tool_planner_capability,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState

AgentType = Literal[
    "architect",
    "lead_engineer",
    "doc_extractor",
    "reviewer_critic",
    "tool_planner",
    "consistency_checker",
]


class ToolPlannerAgent(BaseAgent):
    """Plans tool assignments for each task. Re-invocable per task.

    This agent is deterministic — it does not make LLM calls. It inspects
    the target agent's declared capability and the task's context
    requirements to decide which tools should be assigned.
    """

    _SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("tool_planner")

    # Context-requirement keyword → optional-tool mapping
    _CONTEXT_KEYWORD_TO_TOOLS: Dict[str, List[str]] = {
        "architecture": ["get_symbol_info", "trace_call_chain"],
        "hotspot": ["execute_cypher_query"],
        "entry_point": ["search_code"],
        "symbol_ref": ["get_symbol_info"],
        "references": ["get_symbol_info"],
        "related_files": ["get_related_files"],
        "file_snippet": ["get_file_content"],
        "symbol_details": ["get_symbol_info"],
    }

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_agent_capability(agent_type: AgentType) -> AgentCapability:
        """Return the canonical AgentCapability for a given agent type."""
        registry: Dict[AgentType, AgentCapability] = {
            "architect": architect_capability(),
            "lead_engineer": lead_engineer_capability(),
            "doc_extractor": doc_extractor_capability(),
            "reviewer_critic": reviewer_critic_capability(),
            "tool_planner": tool_planner_capability(),
            "consistency_checker": consistency_checker_capability(),
        }
        cap = registry.get(agent_type)
        if cap is None:
            raise ValueError(f"Unknown agent_type: {agent_type!r}")
        return cap

    def _determine_tools(
        self,
        agent_cap: AgentCapability,
        context_requirements: List[str],
    ) -> List[str]:
        """Determine tool assignments for a task given the target agent's capability.

        Strategy:
        1. Always include all ``required_tools``.
        2. Add ``optional_tools`` whose keywords appear in *context_requirements*.
        3. Every returned tool is guaranteed to be in
           ``required_tools ∪ optional_tools`` (agent-tool consistency property).
        """
        allowed = set(agent_cap.required_tools) | set(agent_cap.optional_tools)

        # Start with required tools
        assigned: List[str] = list(agent_cap.required_tools)
        assigned_set = set(assigned)

        # Scan context requirements for keyword matches → optional tools
        context_text = " ".join(context_requirements).lower()
        for keyword, tools in self._CONTEXT_KEYWORD_TO_TOOLS.items():
            if keyword in context_text:
                for tool in tools:
                    if tool in allowed and tool not in assigned_set:
                        assigned.append(tool)
                        assigned_set.add(tool)

        return assigned

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def capability(self) -> AgentCapability:
        return tool_planner_capability(system_prompt=self._SYSTEM_PROMPT)

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Determine tool assignments for every task in the TODO list.

        When called with a single task dict (containing ``agent_type`` and
        ``context_requirements``), it plans tools for that task.  When the
        full ``todo_list`` is available in *state*, it plans for all tasks
        and returns a ``task_tool_assignments`` mapping.

        Returns:
            Dict with ``task_tool_assignments``: ``{task_id: [tool_names]}``
        """
        todo_list: List[Dict[str, Any] | AgentTask] = state.get("todo_list", [])

        # If no todo_list in state, plan for the single provided task
        if not todo_list:
            todo_list = [task]

        assignments: Dict[str, List[str]] = {}
        for t in todo_list:
            t = cast(Dict[str, Any], t)
            agent_type = t.get("agent_type", "")
            context_reqs: List[str] = t.get("context_requirements", [])
            task_id = t.get("task_id", "")

            try:
                agent_cap = self._get_agent_capability(agent_type)
            except ValueError:
                # Unknown agent type — assign empty tool list
                assignments[task_id] = []
                continue

            assignments[task_id] = self._determine_tools(agent_cap, context_reqs)

        return AgentResult(task_tool_assignments=assignments)

    # ------------------------------------------------------------------
    # Replan capability (Requirement 8.2, 8.3)
    # ------------------------------------------------------------------

    async def replan(
        self,
        task: Dict[str, Any],
        rework_feedback: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Re-plan tool assignments after rework feedback or clarification.

        Enriches the task's context_requirements with signals extracted from
        *rework_feedback* and *clarification_responses*, then re-runs the
        deterministic tool selection.

        Returns:
            Dict with ``tool_assignments``: ``[tool_names]`` for the task.
        """
        agent_type = task.get("agent_type", "")
        context_reqs: List[str] = list(task.get("context_requirements", []))

        # Enrich context requirements from rework feedback
        if rework_feedback:
            context_reqs.append(rework_feedback)

        # Enrich from clarification responses
        clarification_responses: Dict[str, str] = state.get("clarification_responses", {})
        for response in clarification_responses.values():
            if response:
                context_reqs.append(response)

        try:
            agent_cap = self._get_agent_capability(agent_type)
        except ValueError:
            return {"tool_assignments": []}

        tools = self._determine_tools(agent_cap, context_reqs)
        return {"tool_assignments": tools}
