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
from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import ContextData, PlanData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import (
    ApprovalInterruptPayload,
    ArtifactRef,
    BudgetState,
    PhaseFingerprint,
    PlanningSubgraphState,
)
from graph_kb_api.flows.v3.state.workflow_state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator
from graph_kb_api.websocket.plan_events import emit_phase_complete, emit_phase_progress
from graph_kb_api.flows.v3.utils.token_estimation import truncate_to_tokens
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt, sanitize_context_for_prompt

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
        self.step_progress = 0.0

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        budget: BudgetState = state.get("budget", {})
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")

        roadmap: Dict[str, Any] = {}

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="planning",
                step="roadmap",
                message="Generating implementation roadmap",
                progress_pct=0.0,
                client_id=client_id,
            )
        except Exception as e:
            logger.warning(f"RoadmapNode emit_phase_progress failed: {e}")

        if not llm:
            raise RuntimeError("RoadmapNode requires an LLM but none was provided in config.")

        workflow_context: WorkflowContext | None = configurable.get("context")
        tools = []
        if workflow_context and workflow_context.app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools
            tools = get_all_tools(workflow_context.app_context.get_retrieval_settings())

        prompt: str = self._build_roadmap_prompt(context, research)
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        response: AIMessage = await llm_with_tools.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        roadmap = self._parse_roadmap(content)

        artifacts_output: Dict[str, Any] = {}
        if artifact_svc and roadmap:
            ref: ArtifactRef = await artifact_svc.store(
                "plan",
                "roadmap.json",
                json.dumps(roadmap, indent=2),
                roadmap.get("roadmap", {}).get("phases", [{}])[0].get("name", "Implementation roadmap"),
            )
            artifacts_output["plan.roadmap"] = ref

        tokens_used: int = get_token_estimator().count_tokens(json.dumps(roadmap, default=str)) if roadmap else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

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
            json_match = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, KeyError):
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
        self.step_progress = 0.15

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")
        budget: BudgetState = state.get("budget", {})
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        feasibility: Dict[str, Any] = {}

        if not llm:
            raise RuntimeError("FeasibilityNode requires an LLM but none was provided in config.")

        workflow_context: WorkflowContext | None = configurable.get("context")
        tools = []
        if workflow_context and workflow_context.app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools
            tools = get_all_tools(workflow_context.app_context.get_retrieval_settings())

        prompt: str = self._build_feasibility_prompt(context, planning, research=state.get("research", {}))
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        response: AIMessage = await llm_with_tools.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        feasibility: dict[str, Any] = self._parse_feasibility(content)

        tokens_used: int = (
            get_token_estimator().count_tokens(json.dumps(feasibility, default=str)) if feasibility else 0
        )
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

        return NodeExecutionResult.success(
            output={
                "plan": {**planning, "feasibility": feasibility.get("feasibility", {})},
                "budget": new_budget,
            }
        )

    def _build_feasibility_prompt(
        self, context: ContextData, planning: PlanData, research: ResearchData | None = None
    ) -> str:
        from graph_kb_api.flows.v3.utils.token_estimation import truncate_to_tokens

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
                        prompt += f"**Key Insights:**\n" + "\n".join(f"- {ins}" for ins in key_insights[:10]) + "\n"

        return prompt

    def _parse_feasibility(self, content: str) -> Dict[str, Any]:
        try:
            json_match = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, KeyError):
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
        self.step_progress = 0.30

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.decompose_agent import DecomposeAgent
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        budget: BudgetState = state.get("budget", {})
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})
        research: ResearchData = state.get("research", {})

        BudgetGuard.check(budget)

        session_id: str = state.get("session_id", "")
        client_id: str | None = configurable.get("client_id")
        workflow_context: WorkflowContext | None = configurable.get("context")
        if not workflow_context:
            raise RuntimeError("DecomposeNode requires a WorkflowContext but none was provided in config.")

        # Build agent task with research findings and document content included
        agent_task: AgentTask = {
            "description": "Decompose spec into agent-persona-aligned section tasks",
            "task_id": f"decompose_{session_id}_{uuid.uuid4().hex[:8]}",
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

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="planning",
                step="decompose",
                message="Decomposing spec into agent-persona-aligned sections",
                progress_pct=0.30,
                client_id=client_id,
            )
        except Exception as e:
            logger.warning(f"DecomposeNode emit_phase_progress failed: {e}")

        agent = DecomposeAgent(client_id=client_id)
        result: AgentResult = await agent.execute_spec_decomposition(
            task=agent_task, state=state, workflow_context=workflow_context
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
            tasks.append(
                {
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
            )

        # Build DAG edges from dependency_graph
        dag_edges = []
        for src, targets in dep_graph.items():
            for tgt in targets:
                dag_edges.append([src, tgt])

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

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="planning",
                step="decompose",
                message=f"Spec decomposed — {len(task_dag.get('tasks', []))} section tasks created",
                progress_pct=0.40,
                client_id=client_id,
            )
        except Exception as e:
            logger.warning(f"DecomposeNode emit_phase_progress failed: {e}")

        # Store via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        if artifact_svc and task_dag:
            ref = await artifact_svc.store(
                "plan",
                "task_dag.json",
                json.dumps(task_dag, indent=2, default=str),
                f"Task DAG with {len(task_dag.get('tasks', []))} spec section tasks",
            )
            artifacts_output["planning.task_dag"] = ref

        # Agent makes 1 LLM call for spec section identification
        tokens_used: int = get_token_estimator().count_tokens(json.dumps(task_dag, default=str)) if task_dag else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

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
        self.step_progress = 0.50

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        planning = state.get("plan", {})
        task_dag = planning.get("task_dag", {})

        validation_errors = []
        validation_warnings = []

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

    def _has_cycles(self, tasks: list, edges: list) -> bool:
        """Check if the DAG has cycles using DFS."""
        if not tasks or not edges:
            return False

        # Build adjacency list
        adj: Dict[str, list] = {t.get("id"): [] for t in tasks}
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
        self.step_progress = 0.65

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.tool_planner_agent import ToolPlannerAgent
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")
        budget: BudgetState = state.get("budget", {})
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
        workflow_context: WorkflowContext | None = configurable.get("context")
        if not workflow_context:
            raise RuntimeError("AssignNode requires a WorkflowContext but none was provided in config.")

        try:
            result: AgentResult = await tool_planner.execute(
                task={},
                state=agent_state,
                workflow_context=workflow_context,
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
        if llm and assignments:
            try:
                prompt: str = self._build_refine_prompt(assignments)
                response: AIMessage = await llm.ainvoke(prompt)
                raw_content = response.content if hasattr(response, "content") else str(response)
                content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
                refined = self._parse_assignments(content)
                if refined.get("assignments"):
                    assignments = refined["assignments"]
                llm_calls = 1
            except Exception as e:
                logger.debug(f"AssignNode LLM refinement skipped: {e}")

        tokens_used: int = (
            get_token_estimator().count_tokens(json.dumps(assignments, default=str)) if assignments else 0
        )
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=llm_calls, tokens_used=tokens_used)

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

    def _build_refine_prompt(self, assignments: list) -> str:
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
            json_match = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, KeyError):
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
        self.step_progress = 0.80

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")
        budget: BudgetState = state.get("budget", {})
        planning: PlanData = state.get("plan", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        alignment: Dict[str, Any] = {}

        if not llm:
            raise RuntimeError("AlignNode requires an LLM but none was provided in config.")

        prompt: str = self._build_align_prompt(context, planning)
        response: AIMessage = await llm.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        alignment: dict[str, Any] = self._parse_alignment(content)

        tokens_used: int = get_token_estimator().count_tokens(json.dumps(alignment, default=str)) if alignment else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

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
        return f"""You are a requirements alignment specialist. Verify that the plan meets all
requirements and constraints.

## Specification: {spec_name}
## Constraints: {constraints}
## Plan: {roadmap}

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

    def _parse_alignment(self, content: str) -> Dict[str, Any]:
        try:
            json_match = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result.get("alignment", {})
        except (json.JSONDecodeError, KeyError):
            pass
        return {
            "is_aligned": True,
            "constraints_met": [],
            "constraints_violated": [],
            "adjustments_needed": [],
            "coverage_score": 0.7,
        }


class PlanningApprovalNode(SubgraphAwareNode[PlanningSubgraphState]):
    """Approval gate for planning phase completion.

    Presents the complete plan to user for approval before proceeding
    to orchestration. Uses interrupt() for user confirmation.
    """

    def __init__(self) -> None:
        super().__init__(node_name="planning_approval")
        self.phase = "planning"
        self.step_name = "approval"
        self.step_progress = 1.0

    async def _execute_step(self, state: PlanningSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        planning = state.get("plan", {})
        context = state.get("context", {})

        roadmap = planning.get("roadmap", {})
        feasibility = planning.get("feasibility", {})
        task_dag = planning.get("task_dag", {})
        alignment = planning.get("alignment", {})

        tasks = task_dag.get("tasks", [])

        summary = {
            "spec_name": context.get("spec_name", "Unknown"),
            "phases_count": len(roadmap.get("phases", [])),
            "tasks_count": len(tasks),
            "feasibility_score": feasibility.get("overall_score", 0.7),
            "alignment_score": alignment.get("coverage_score", 0.7),
            "go_no_go": feasibility.get("go_no_go", "go"),
        }

        context_items = await self._load_context_items(state.get("session_id"), state["research"])
        payload: ApprovalInterruptPayload = {
            "type": "approval",
            "phase": "planning",
            "step": "approval",
            "summary": summary,
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
            "message": (
                f"Planning complete with {summary['tasks_count']} tasks. "
                f"Feasibility: {summary['feasibility_score']:.0%}. Approve to start execution?"
            ),
            "artifacts": self._serialize_artifacts(state["artifacts"]),
            "options": [
                {"id": "approve", "label": "Approve & Start Execution"},
                {"id": "revise", "label": "Request Revisions"},
                {"id": "reject", "label": "Reject & Restart"},
            ],
            "context_items": context_items,
        }
        approval_response: Dict[str, Any] = interrupt(payload)

        decision = approval_response.get("decision", "approve")
        feedback = approval_response.get("feedback", "")

        output: Dict[str, Any] = {
            "plan": {
                **planning,
                "approved": decision == "approve",
                "approval_decision": decision,
                "approval_feedback": feedback,
            }
        }

        if decision == "approve":
            output["completed_phases"] = {"planning": True}
            # Store fingerprint for dirty-detection on backward navigation
            fp_hash: str = FingerprintTracker.compute_phase_data_fingerprint("planning", output["plan"])
            existing_fps: dict[str, PhaseFingerprint] = state.get("fingerprints", {})
            output["fingerprints"] = FingerprintTracker.update_fingerprint(
                existing_fps,
                "planning",
                fp_hash,
                [],
            )
            # Emit plan.phase.complete (GAP 9)
            try:
                session_id: str = state.get("session_id", "")
                configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
                client_id: str | None = configurable.get("client_id")
                await emit_phase_complete(
                    session_id=session_id,
                    phase="planning",
                    result_summary=f"Planning approved with {summary['tasks_count']} tasks",
                    duration_s=0.0,
                    client_id=client_id,
                )
            except Exception:
                pass  # fire-and-forget
        elif decision == "revise":
            output["plan"]["needs_revision"] = True
        elif decision == "reject":
            output["plan"]["rejected"] = True
            output["workflow_status"] = "rejected"
            output["paused_phase"] = "planning"
            output["error"] = {
                "message": "Planning was rejected by user.",
                "code": "REJECTED",
                "phase": "planning",
            }

        return NodeExecutionResult.success(output=output)
