"""Planning subgraph nodes for the /plan command.

RoadmapNode, FeasibilityNode, DecomposeNode, ValidateDagNode, AssignNode, AlignNode, PlanningApprovalNode.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, cast

from langchain.messages import AIMessage
from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents import AgentResult, AgentTask
from graph_kb_api.flows.v3.agents.personas.prompt_manager import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.nodes.plan.base_approval_node import BaseApprovalNode
from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import ContextData, PlanData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import (
    PLANNING_PROGRESS,
    ArtifactRef,
    BudgetState,
    InterruptOption,
    PlanningSubgraphState,
    WorkflowError,
)
from graph_kb_api.flows.v3.state.workflow_state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt, sanitize_context_for_prompt
from graph_kb_api.flows.v3.utils.json_parsing import parse_json_from_llm
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator, truncate_to_tokens
from graph_kb_api.websocket.plan_events import emit_phase_progress

logger = logging.getLogger(__name__)


class RoadmapNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Generates a high-level roadmap for the plan.

    Uses LLM to create a phased implementation roadmap based on
    research findings and context. Stores full roadmap via ArtifactService.
    """

    def __init__(self) -> None:
        super().__init__(node_name="roadmap")
        self.phase = "planning"
        self.step_name = "roadmap"
        self.step_progress = PLANNING_PROGRESS["roadmap"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        roadmap: Dict[str, Any] = {}

        await self._emit_progress(ctx, "roadmap", 0.0, "Generating implementation roadmap")

        llm = ctx.require_llm

        tools = []
        if ctx.workflow_context and ctx.workflow_context.app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools
            tools = get_all_tools(ctx.workflow_context.app_context.get_retrieval_settings())

        prompt: str = self._build_roadmap_prompt(context, research)
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        response: AIMessage = await llm_with_tools.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        roadmap = self._parse_roadmap(content)

        artifacts_output: Dict[str, Any] = {}
        if ctx.artifact_service and roadmap:
            ref: ArtifactRef = await ctx.artifact_service.store(
                "plan",
                "roadmap.json",
                json.dumps(roadmap, indent=2),
                roadmap.get("roadmap", {}).get("phases", [{}])[0].get("name", "Implementation roadmap"),
            )
            artifacts_output["plan.roadmap"] = ref

        new_budget = self._decrement_budget(budget, json.dumps(roadmap, default=str))

        return NodeExecutionResult.success(
            output={
                "plan": {"roadmap": roadmap.get("roadmap", {})},
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )

    def _build_roadmap_prompt(self, context: ContextData, research: ResearchData) -> str:
        context_json: str = json.dumps(sanitize_context_for_prompt(context), indent=2, default=str)
        findings_json: str = json.dumps(research.get("findings", {}), indent=2, default=str)
        base_prompt: str = get_agent_prompt_manager().get_prompt("plan_roadmap", subdir="nodes")
        prompt = f"{base_prompt}\n\n## Context\n{context_json}\n\n## Research Findings\n{findings_json}"

        prompt = append_document_context_to_prompt(prompt, context)

        return prompt

    def _parse_roadmap(self, content: str) -> Dict[str, Any]:
        try:
            parsed = parse_json_from_llm(content)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        return {"roadmap": {"phases": [], "critical_path": []}}


class FeasibilityNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Assesses feasibility of the roadmap.

    Evaluates technical, timeline, and resource feasibility.
    Flags high-risk areas and suggests mitigations.
    """

    def __init__(self) -> None:
        super().__init__(node_name="feasibility")
        self.phase = "planning"
        self.step_name = "feasibility"
        self.step_progress = PLANNING_PROGRESS["feasibility"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        feasibility: Dict[str, Any] = {}

        llm = ctx.require_llm

        tools = []
        if ctx.workflow_context and ctx.workflow_context.app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools
            tools = get_all_tools(ctx.workflow_context.app_context.get_retrieval_settings())

        prompt: str = self._build_feasibility_prompt(context, planning, research=state.get("research", {}))
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        response: AIMessage = await llm_with_tools.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        feasibility: dict[str, Any] = self._parse_feasibility(content)

        new_budget = self._decrement_budget(budget, json.dumps(feasibility, default=str))

        return NodeExecutionResult.success(
            output={
                "plan": {**planning, "feasibility": feasibility.get("feasibility", {})},
                "budget": new_budget,
            }
        )

    def _build_feasibility_prompt(
        self, context: ContextData, planning: PlanData, research: ResearchData | None = None
    ) -> str:

        constraints: str = context.get("constraints", "No specific constraints")
        roadmap_json: str = json.dumps(planning.get("roadmap", {}), indent=2, default=str)
        base_prompt: str = get_agent_prompt_manager().get_prompt("plan_feasibility", subdir="nodes")
        prompt = f"{base_prompt}\n\n## Constraints\n{constraints}\n\n## Roadmap\n{roadmap_json}"

        # Include research findings so feasibility can account for technical risks
        if research:
            findings = research.get("findings", {})
            if findings:
                findings_summary = findings.get("summary", "")
                key_insights = findings.get("key_insights", [])
                if findings_summary or key_insights:
                    prompt += "\n\n## Research Findings\n"
                    if findings_summary:
                        prompt += f"**Summary:** {truncate_to_tokens(findings_summary, 1000)}\n"
                    if key_insights:
                        prompt += "**Key Insights:**\n" + "\n".join(f"- {ins}" for ins in key_insights[:10]) + "\n"

        prompt = append_document_context_to_prompt(prompt, context)

        return prompt

    def _parse_feasibility(self, content: str) -> Dict[str, Any]:
        try:
            parsed = parse_json_from_llm(content)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        return {"feasibility": {"overall_score": 0.7, "go_no_go": "go"}}


class DecomposeNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Decomposes the spec into agent-persona-aligned section tasks.

    Uses DecomposeAgent.execute_spec_decomposition() to produce tasks where
    each task represents a spec section assigned to a specialized agent
    persona that will research and draft it.
    """

    def __init__(self) -> None:
        super().__init__(node_name="decompose")
        self.phase = "planning"
        self.step_name = "decompose"
        self.step_progress = PLANNING_PROGRESS["decompose"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.decompose_agent import DecomposeAgent

        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})
        research: ResearchData = state.get("research", {})

        BudgetGuard.check(budget)

        if not ctx.workflow_context:
            raise RuntimeError("DecomposeNode requires a WorkflowContext but none was provided in config.")

        # Build agent task with research findings and document content included
        agent_task: AgentTask = {
            "description": "Decompose spec into agent-persona-aligned section tasks",
            "task_id": f"decompose_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "context": {
                "roadmap": planning.get("roadmap", {}),
                "user_explanation": context.get("user_explanation", ""),
                "constraints": context.get("constraints", {}),
                "spec_name": context.get("spec_name", ""),
                "research_findings": research.get("findings", {}),
                "uploaded_document_contents": context.get("uploaded_document_contents", []),
                "document_section_index": context.get("document_section_index", []),
                "reference_documents": context.get("reference_documents", []),
            },
        }

        task_dag: Dict[str, Any] = {}

        await self._emit_progress(ctx, "decompose", 0.30, "Decomposing spec into agent-persona-aligned sections")

        agent = DecomposeAgent(client_id=ctx.client_id)
        result: AgentResult = await agent.execute_spec_decomposition(
            task=agent_task, state=state, workflow_context=ctx.workflow_context
        )

        # Parse the JSON output from the agent
        output_str = result.get("output", "{}")
        if isinstance(output_str, str):
            decomposition = json.loads(output_str)
        else:
            decomposition = output_str

        spec_sections = decomposition.get("spec_sections", [])
        dep_graph = decomposition.get("dependency_graph", {})

        # Map spec sections → task DAG format
        tasks = []
        for section in spec_sections:
            task_entry: dict[str, Any] = {
                "id": section.get("id", ""),
                "name": section.get("name", ""),
                "description": section.get("description", ""),
                "agent_type": section.get("agent_type", "architect"),
                "section_type": section.get("section_type", "analysis_and_draft"),
                "spec_section": section.get("spec_section", "general"),
                "relevant_docs": section.get("relevant_docs", []),
                "context_requirements": section.get("context_requirements", []),
                "dependencies": section.get("dependencies", []),
                "priority": section.get("priority", "medium"),
                "tools_required": section.get("tools_required", ["llm"]),
            }
            # Pass through scope_contract and reading_order when present
            if "scope_contract" in section:
                task_entry["scope_contract"] = section["scope_contract"]
            if "reading_order" in section:
                task_entry["reading_order"] = section["reading_order"]
            tasks.append(task_entry)

        # Build DAG edges from dependency_graph.
        # dep_graph maps section_id → [prerequisite_ids], so each edge
        # should point FROM the prerequisite TO the dependent section:
        #   [prerequisite, dependent]  i.e.  [tgt, src]
        dag_edges = []
        for src, targets in dep_graph.items():
            for tgt in targets:
                dag_edges.append([tgt, src])

        entry_tasks = [t["id"] for t in tasks if not t.get("dependencies")]
        exit_tasks = (
            [t["id"] for t in tasks if t["id"] not in {e[0] for e in dag_edges}]
            if dag_edges
            else [t["id"] for t in tasks[-1:]]
        )

        task_dag: dict[str, Any] = {
            "tasks": tasks,
            "dag_edges": dag_edges,
            "entry_tasks": entry_tasks,
            "exit_tasks": exit_tasks,
            "decomposition_type": "spec_section",
            "total_sections": len(spec_sections),
            "total_tasks": len(tasks),
        }

        await self._emit_progress(
            ctx, "decompose", 0.40,
            f"Spec decomposed — {len(task_dag.get('tasks', []))} section tasks created",
        )

        # Store via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        if ctx.artifact_service and task_dag:
            ref = await ctx.artifact_service.store(
                "plan",
                "task_dag.json",
                json.dumps(task_dag, indent=2, default=str),
                f"Task DAG with {len(task_dag.get('tasks', []))} spec section tasks",
            )
            artifacts_output["planning.task_dag"] = ref

        # Agent makes 1 LLM call for spec section identification
        new_budget = self._decrement_budget(budget, json.dumps(task_dag, default=str))

        return NodeExecutionResult.success(
            output={
                "plan": {**planning, "task_dag": task_dag},
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )


class ValidateDagNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Validates the decomposed task DAG for correctness.

    Checks for cycles, orphan tasks, and missing dependencies.
    Returns validation status and any errors found.
    """

    def __init__(self) -> None:
        super().__init__(node_name="validate_dag")
        self.phase = "planning"
        self.step_name = "validate_dag"
        self.step_progress = PLANNING_PROGRESS["validate_dag"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        planning: PlanData = state.get("plan", {})
        task_dag = planning.get("task_dag", {})

        validation_errors: list[dict[str, Any]] = []
        validation_warnings: list[dict[str, Any]] = []

        tasks = task_dag.get("tasks", [])
        dag_edges = task_dag.get("dag_edges", [])
        task_ids = {t.get("id") for t in tasks}

        # Check for cycles using DFS
        if self._has_cycles(tasks, dag_edges):
            validation_errors.append({"type": "cycle", "message": "DAG contains cycles"})

        # Check for orphan tasks (no dependencies and no dependents)
        edge_task_ids = set()
        for edge in dag_edges:
            edge_task_ids.update(edge)
        orphan_tasks = task_ids - edge_task_ids
        if orphan_tasks and len(orphan_tasks) > 1:
            validation_warnings.append(
                {
                    "type": "orphans",
                    "message": f"Found {len(orphan_tasks)} orphan tasks with no dependencies",
                    "tasks": list(orphan_tasks),
                }
            )

        # Check for missing task references in edges
        for edge in dag_edges:
            for task_id in edge:
                if task_id not in task_ids:
                    validation_errors.append(
                        {
                            "type": "missing_task",
                            "message": f"Edge references non-existent task: {task_id}",
                        }
                    )

        is_valid: bool = len(validation_errors) == 0

        if not is_valid:
            # Return error state instead of raising — allows subgraph to
            # handle gracefully without halting the entire workflow.
            error_messages = "; ".join(e.get("message", "") for e in validation_errors)
            logger.warning("DAG validation failed: %s", error_messages)
            return NodeExecutionResult.success(
                output={
                    "plan": {
                        **planning,
                        "dag_validation": {
                            "is_valid": False,
                            "errors": validation_errors,
                            "warnings": validation_warnings,
                        },
                    },
                }
            )

        return NodeExecutionResult.success(
            output={
                "plan": {
                    **planning,
                    "dag_validation": {
                        "is_valid": True,
                        "errors": validation_errors,
                        "warnings": validation_warnings,
                    },
                }
            }
        )

    def _has_cycles(self, tasks: list[Dict[str, Any]], edges: list[list[str]]) -> bool:
        """Check if the DAG has cycles using DFS."""
        if not tasks or not edges:
            return False

        # Build adjacency list
        adj: Dict[str, list[str]] = {t.get("id"): [] for t in tasks}
        for src, dst in edges:
            if src in adj:
                adj[src].append(dst)

        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for task_id in adj:
            if task_id not in visited:
                if dfs(task_id):
                    return True
        return False


class AssignNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Assigns agents and tools to tasks via ToolPlannerAgent.execute().

    Calls the ToolPlannerAgent (deterministic, no LLM) to map each task
    to an appropriate agent type and required tools based on task
    characteristics and agent capabilities.
    """

    def __init__(self) -> None:
        super().__init__(node_name="assign")
        self.phase = "planning"
        self.step_name = "assign"
        self.step_progress = PLANNING_PROGRESS["assign"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.tool_planner_agent import ToolPlannerAgent

        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        planning: PlanData = state.get("plan", {})

        BudgetGuard.check(budget)

        task_dag = planning.get("task_dag", {})
        tasks = task_dag.get("tasks", [])

        if not tasks:
            logger.warning("AssignNode: task_dag has no tasks, skipping assignment")
            return NodeExecutionResult.success(
                output={
                    "plan": {**planning, "assignments": []},
                    "budget": budget,
                }
            )

        # Build the todo_list the ToolPlannerAgent expects
        todo_list = []
        for t in tasks:
            todo_list.append(
                {
                    "task_id": t.get("id", ""),
                    "agent_type": self._map_agent_type(t.get("agent_type", "general")),
                    "context_requirements": t.get("tools_required", []) + [t.get("description", "")],
                    "description": t.get("description", ""),
                    "name": t.get("name", ""),
                }
            )

        # Call ToolPlannerAgent (deterministic — no LLM needed)
        tool_planner = ToolPlannerAgent()
        agent_state: UnifiedSpecState = cast("UnifiedSpecState", {"todo_list": todo_list})
        if not ctx.workflow_context:
            raise RuntimeError("AssignNode requires a WorkflowContext but none was provided in config.")

        try:
            result: AgentResult = await tool_planner.execute(
                task={},
                state=agent_state,
                workflow_context=ctx.workflow_context,
            )
            tool_assignments = result.get("task_tool_assignments", {})
        except Exception as e:
            logger.warning(f"AssignNode ToolPlannerAgent failed: {e}")
            tool_assignments = {}

        # Build assignments list combining agent_type + tool assignments
        assignments = []
        for t in tasks:
            task_id = t.get("id", "")
            agent_type = t.get("agent_type", "general")
            tools = tool_assignments.get(task_id, ["llm"])
            assignments.append(
                {
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "tools": tools,
                    "skills_required": t.get("tools_required", []),
                    "reasoning": f"Assigned by ToolPlannerAgent (agent: {agent_type})",
                }
            )

        # If we also have an LLM, refine assignments with an LLM pass
        llm_calls = 0
        if ctx.llm and assignments:
            try:
                prompt: str = self._build_refine_prompt(assignments)
                response: AIMessage = await ctx.llm.ainvoke(prompt)
                raw_content = response.content if hasattr(response, "content") else str(response)
                content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
                refined = self._parse_assignments(content)
                if refined.get("assignments"):
                    assignments = refined["assignments"]
                llm_calls = 1
            except Exception as e:
                logger.debug(f"AssignNode LLM refinement skipped: {e}")

        new_budget = self._decrement_budget(budget, json.dumps(assignments, default=str), llm_calls=llm_calls)

        return NodeExecutionResult.success(
            output={
                "plan": {**planning, "assignments": assignments},
                "budget": new_budget,
            }
        )

    @staticmethod
    def _map_agent_type(raw_type: str) -> str:
        """Map plan task agent_type to ToolPlannerAgent's AgentType literals."""
        mapping = {
            "backend": "architect",
            "frontend": "lead_engineer",
            "fullstack": "architect",
            "general": "architect",
            "architect": "architect",
            "research": "architect",
            "lead_engineer": "lead_engineer",
            "code_generator": "lead_engineer",
            "devops": "architect",
            "qa": "reviewer_critic",
        }
        return mapping.get(raw_type, "architect")

    def _build_refine_prompt(self, assignments: list[Dict[str, Any]]) -> str:
        assignments_json = json.dumps(assignments, indent=2, default=str)
        return f"""You are a task assignment specialist. Review and refine these agent/tool assignments.
Ensure each task has the most appropriate agent type and tools.

Agent types: backend, frontend, fullstack, devops, qa, general
Tool categories: llm, websearch, vector_store, graph_db, file_system, code_editor

Current assignments:
{assignments_json}

Return JSON with this structure:
{{
    "assignments": [
        {{
            "task_id": "task_1",
            "agent_type": "backend",
            "tools": ["llm", "code_editor"],
            "skills_required": ["python", "api_design"],
            "reasoning": "Task requires API development"
        }}
    ]
}}
"""

    def _parse_assignments(self, content: str) -> Dict[str, Any]:
        try:
            parsed = parse_json_from_llm(content)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        return {"assignments": []}


class AlignNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Aligns plan with requirements and constraints.

    Verifies the plan meets all requirements and constraints from context.
    Identifies gaps and suggests adjustments.
    """

    def __init__(self) -> None:
        super().__init__(node_name="align")
        self.phase = "planning"
        self.step_name = "align"
        self.step_progress = PLANNING_PROGRESS["align"]

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        alignment: Dict[str, Any] = {}

        llm = ctx.require_llm

        prompt: str = self._build_align_prompt(context, planning)
        response: AIMessage = await llm.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        alignment: dict[str, Any] = self._parse_alignment(content)

        new_budget = self._decrement_budget(budget, json.dumps(alignment, default=str))

        return NodeExecutionResult.success(
            output={
                "plan": {**planning, "alignment": alignment},
                "budget": new_budget,
            }
        )

    def _build_align_prompt(self, context: ContextData, planning: PlanData) -> str:
        constraints: str = context.get("constraints", "No specific constraints")
        spec_name: str = context.get("spec_name", "Feature")
        roadmap: str = json.dumps(planning.get("roadmap", {}), indent=2, default=str)
        task_dag = planning.get("task_dag", {})
        tasks_summary: str = json.dumps(
            [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "description": t.get("description"),
                    "spec_section": t.get("spec_section"),
                    "dependencies": t.get("dependencies", []),
                }
                for t in task_dag.get("tasks", [])
            ],
            indent=2,
            default=str,
        )
        prompt = f"""You are a requirements alignment specialist. Verify that the plan meets all
requirements and constraints.

## Specification: {spec_name}
## Constraints: {constraints}
## Roadmap: {roadmap}
## Task Breakdown ({task_dag.get("total_tasks", 0)} tasks):
{tasks_summary}

Return JSON with this structure:
{{
    "alignment": {{
        "is_aligned": true,
        "constraints_met": ["constraint 1"],
        "constraints_violated": [],
        "adjustments_needed": [],
        "coverage_score": 0.9
    }}
}}
"""
        prompt = append_document_context_to_prompt(prompt, context)
        return prompt

    def _parse_alignment(self, content: str) -> Dict[str, Any]:
        try:
            parsed = parse_json_from_llm(content)
            if isinstance(parsed, dict):
                return parsed.get("alignment", parsed)
        except ValueError:
            pass
        return {
            "is_aligned": True,
            "constraints_met": [],
            "constraints_violated": [],
            "adjustments_needed": [],
            "coverage_score": 0.7,
        }


class PlanningApprovalNode(BaseApprovalNode[PlanningSubgraphState]):
    """Approval gate for planning phase completion.

    Presents the complete plan to user for approval before proceeding
    to orchestration. Extends BaseApprovalNode with planning-specific hooks.
    """

    phase_data_key = "plan"

    def __init__(self) -> None:
        super().__init__(node_name="planning_approval")
        self.phase = "planning"
        self.step_name = "approval"
        self.step_progress = PLANNING_PROGRESS["approval"]

    def _build_summary(self, state: PlanningSubgraphState) -> dict[str, Any]:
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        roadmap = planning.get("roadmap", {})
        feasibility = planning.get("feasibility", {})
        task_dag = planning.get("task_dag", {})
        alignment = planning.get("alignment", {})

        tasks = task_dag.get("tasks", [])

        return {
            "spec_name": context.get("spec_name", "Unknown"),
            "phases_count": len(roadmap.get("phases", [])),
            "tasks_count": len(tasks),
            "feasibility_score": feasibility.get("overall_score", 0.7),
            "alignment_score": alignment.get("coverage_score", 0.7),
            "go_no_go": feasibility.get("go_no_go", "go"),
        }

    def _build_payload_extras(self, state: PlanningSubgraphState, summary: dict[str, Any]) -> dict[str, Any]:
        planning: PlanData = state.get("plan", {})
        task_dag = planning.get("task_dag", {})
        tasks = task_dag.get("tasks", [])
        return {
            "tasks": [
                {
                    "id": t.get("id", ""),
                    "name": t.get("name", t.get("title", "")),
                    "description": t.get("description", ""),
                    "agent_type": t.get("agent_type", ""),
                    "priority": t.get("priority", "medium"),
                    "dependencies": t.get("dependencies", []),
                }
                for t in tasks
            ],
        }

    def _get_approval_options(self) -> list[InterruptOption]:
        return [
            {"id": "approve", "label": "Approve & Start Execution"},
            {"id": "revise", "label": "Request Revisions"},
            {"id": "reject", "label": "Reject & Restart"},
        ]

    def _get_approval_message(self, summary: dict[str, Any]) -> str:
        return (
            f"Planning complete with {summary['tasks_count']} tasks. "
            f"Feasibility: {summary['feasibility_score']:.0%}. Approve to start execution?"
        )

    def _process_approve(self, state: PlanningSubgraphState, feedback: str) -> dict[str, Any]:
        planning: PlanData = state.get("plan", {})
        return {
            "plan": {
                **planning,
                "approved": True,
                "approval_decision": "approve",
                "approval_feedback": feedback,
            },
        }

    def _process_revise(self, state: PlanningSubgraphState, feedback: str) -> dict[str, Any]:
        planning: PlanData = state.get("plan", {})
        return {
            "plan": {
                **planning,
                "approved": False,
                "approval_decision": "revise",
                "approval_feedback": feedback,
                "needs_revision": True,
            },
        }

    def _process_reject(self, state: PlanningSubgraphState, feedback: str) -> dict[str, Any]:
        planning: PlanData = state.get("plan", {})
        return {
            "plan": {
                **planning,
                "approved": False,
                "approval_decision": "reject",
                "approval_feedback": feedback,
                "rejected": True,
            },
            "workflow_status": "rejected",
            "paused_phase": "planning",
            "error": WorkflowError(
                message="Planning was rejected by user.",
                code="REJECTED",
                phase="planning",
            ),
        }
