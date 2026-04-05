"""
Architect agent for the multi-agent feature spec workflow.

Handles high-level design sections — architecture, component diagrams,
system boundaries, data flow. Reports confidence score with each draft.

Also handles orchestration of worker agents with a critique loop pattern:
- Dispatch tasks to appropriate worker agents
- Critique worker outputs
- Iterate up to MAX_CRITIQUE_ITERATIONS until approved
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, cast

from langchain.messages import AIMessage

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask, CritiqueResult, architect_capability
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.agent_helpers import build_prompt, compute_confidence
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

MAX_CRITIQUE_ITERATIONS = 3


_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("architect")


logger = EnhancedLogger(__name__)


class ArchitectAgent(BaseAgent):
    """Generates architecture and design sections with confidence scoring.

    Extends BaseAgent with AgentCapability for architecture tasks.
    Uses Graph KB tools: search_code, get_symbol_info, trace_call_chain.
    """

    def __init__(self) -> None:
        pass

    @property
    def capability(self) -> AgentCapability:
        return architect_capability(system_prompt=_SYSTEM_PROMPT)

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute architecture task and return draft with confidence score.

        Returns:
            Dict with:
            - agent_draft: str — the generated section content
            - confidence_score: float 0.0-1.0
            - confidence_rationale: str — explanation of confidence level
        """
        agent_context: Dict[str, Any] = state.get("agent_context", {}) or {}
        user_prompt: str = build_prompt(task, agent_context)
        confidence_score, confidence_rationale = compute_confidence(agent_context)

        # Attempt LLM call
        if workflow_context is None:
            raise RuntimeError("ArchitectAgent requires a WorkflowContext")
        agent_draft: str = await self._generate_draft(user_prompt, state, workflow_context)

        return AgentResult(
            {
                "agent_draft": agent_draft,
                "confidence_score": confidence_score,
                "confidence_rationale": confidence_rationale,
            }
        )

    async def _generate_draft(
        self, user_prompt: str, state: Mapping[str, Any], workflow_context: WorkflowContext
    ) -> str:
        """Call the LLM to generate the draft. Gracefully handles missing LLM."""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        all_tools = state.get("available_tools", [])
        assigned_tools: list[Any] = [
            t for t in all_tools if hasattr(t, "name") and t.name in self.capability.required_tools
        ]

        llm: LLMService = workflow_context.require_llm

        try:
            response: AIMessage = await llm.bind_tools(assigned_tools).ainvoke(messages)
            if hasattr(response, "content"):
                return str(response.content)
            return str(response)
        except Exception as exc:
            return f"[Draft generation failed: {exc}]\n\n{user_prompt}"

    # ── Orchestration Methods (O1-O9) ─────────────────────────────────────

    async def orchestrate(
        self,
        plan: Dict[str, Any],
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
        worker_registry: Optional[Dict[str, BaseAgent]] = None,
    ) -> Dict[str, Any]:
        """Orchestrate worker agents with dispatch/critique loop (O1-O9).

        This method implements the orchestration pattern from the workflow spec:
        - O1: Dispatch task to worker agent
        - O2: Worker agent executes
        - O3: Architect critiques result
        - O4: Check if approved
        - O5-O6: If not approved and iteration < MAX, add feedback and retry
        - O7-O9: Task complete, proceed to next task

        Args:
            plan: Plan data containing agent_assignments list
            context: Context data from earlier phases
            worker_registry: Optional dict mapping agent_type to agent instances
            workflow_context: Application context with LLM, graph_store, etc.

        Returns:
            Dict with:
            - task_results: List of completed task outputs
            - task_iterations: Dict mapping task_id to iteration history
            - all_complete: bool indicating all tasks completed successfully
        """
        agent_assignments = plan.get("agent_assignments", [])
        task_results: List[Dict[str, Any]] = []
        task_iterations: Dict[str, List[Dict[str, Any]]] = {}

        for assignment in agent_assignments:
            task_id = assignment.get("task_id", "unknown")
            agent_type = assignment.get("agent_type", "generic")
            tools = assignment.get("tools", [])
            task_iterations[task_id] = []

            iteration = 0
            task_result = None
            approved = False

            while iteration < MAX_CRITIQUE_ITERATIONS:
                # O1: Dispatch to worker agent
                worker = self._get_worker_agent(agent_type, worker_registry)

                # O2: Worker executes
                task_result = await self._dispatch_to_worker(
                    worker=worker,
                    assignment=assignment,
                    context=context,
                    tools=tools,
                    workflow_context=workflow_context,
                    critique_feedback=task_iterations[task_id][-1].get("feedback")
                    if task_iterations[task_id]
                    else None,
                )

                # O3: Architect critiques
                critique = await self.critique_task(
                    task_result=task_result,
                    assignment=assignment,
                    original_context=context,
                    workflow_context=workflow_context,
                )

                approved = critique.get("approved", False)

                # Record iteration
                task_iterations[task_id].append(
                    {
                        "iteration": iteration + 1,
                        "result": task_result,
                        "critique": critique,
                        "approved": approved,
                        "feedback": critique.get("feedback", ""),
                    }
                )

                # O4: Check if approved
                if approved:
                    logger.info(f"Task {task_id} approved after {iteration + 1} iteration(s)")
                    break

                # O5-O6: Add feedback and retry
                iteration += 1
                logger.info(f"Task {task_id} iteration {iteration}: not approved, retrying")

            # O7: Task complete (approved or max iterations reached)
            task_results.append(
                {
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "result": task_result,
                    "iterations": iteration + 1,
                    "approved": approved,
                }
            )

        # O9: All tasks complete
        all_approved: bool = all(t.get("approved", False) for t in task_results)

        return {
            "task_results": task_results,
            "task_iterations": task_iterations,
            "all_complete": all_approved,
            "total_tasks": len(agent_assignments),
            "approved_count": sum(1 for t in task_results if t.get("approved")),
        }

    def _get_worker_agent(
        self,
        agent_type: str,
        worker_registry: Optional[Dict[str, BaseAgent]],
    ) -> Optional[BaseAgent]:
        """O1: Get the appropriate worker agent for the task type."""
        if worker_registry and agent_type in worker_registry:
            return worker_registry[agent_type]

        # Default: return None, will use placeholder execution
        logger.warning(f"No worker agent found for type: {agent_type}")
        return None

    async def _dispatch_to_worker(
        self,
        worker: Optional[BaseAgent],
        assignment: Dict[str, Any],
        context: Dict[str, Any],
        tools: List[str],
        workflow_context: WorkflowContext,
        critique_feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """O2: Dispatch task to worker agent with tools."""
        task: AgentTask = {
            "task_id": assignment.get("task_id", ""),
            "description": assignment.get("description", ""),
            "tools": tools,
        }

        # Add critique feedback if this is a retry
        if critique_feedback:
            context = {**context, "critique_feedback": critique_feedback}

        if worker is None:
            # Placeholder execution when no worker available
            return {
                "task_id": assignment.get("task_id"),
                "output": f"[Placeholder output for task {assignment.get('task_id')}]",
                "status": "placeholder",
            }

        try:
            result: AgentResult = await worker.execute(
                task=task,
                state=cast("UnifiedSpecState", {"agent_context": context}),
                workflow_context=workflow_context,
            )
            return {
                "task_id": assignment.get("task_id"),
                "output": result,
                "status": "completed",
            }
        except Exception as exc:
            logger.error(f"Worker execution failed: {exc}")
            return {
                "task_id": assignment.get("task_id"),
                "output": None,
                "error": str(exc),
                "status": "failed",
            }

    async def critique_task(
        self,
        task_result: Dict[str, Any],
        assignment: Dict[str, Any],
        original_context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> CritiqueResult:
        """O3: Critique the worker's output.

        Returns:
            Dict with:
            - approved: bool
            - feedback: str (if not approved)
            - score: float 0-1
        """
        output = task_result.get("output")

        # Handle failed or placeholder results
        if task_result.get("status") == "failed":
            return {
                "approved": False,
                "feedback": f"Task execution failed: {task_result.get('error')}",
                "score": 0.0,
            }

        if task_result.get("status") == "placeholder":
            # Approve placeholders for now (no real worker available)
            return {
                "approved": True,
                "feedback": "Placeholder approved (no worker agent available)",
                "score": 0.5,
            }

        # Use LLM to critique
        return await self._llm_critique(
            output=output,
            assignment=assignment,
            original_context=original_context,
            workflow_context=workflow_context,
        )

    async def _llm_critique(
        self,
        output: Any,
        assignment: Dict[str, Any],
        original_context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> CritiqueResult:
        """Use LLM to critique worker output."""
        llm: LLMService = workflow_context.require_llm
        try:
            critique_prompt_template = get_agent_prompt_manager().get_prompt("architect_critique")
            prompt = critique_prompt_template.format(
                task_id=assignment.get("task_id", "unknown"),
                task_name=assignment.get("task_name", "Unknown"),
                expected_complexity=assignment.get("complexity", "unknown"),
                context=json.dumps(original_context, indent=2, default=str),
                worker_output=json.dumps(output, indent=2, default=str) if isinstance(output, dict) else str(output),
            )

            response: AIMessage = await llm.ainvoke(
                [
                    {"role": "system", "content": "You are a precise code reviewer. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ]
            )

            content = str(response.content) if hasattr(response, "content") else str(response)

            # Strip markdown code fences if present
            content = re.sub(r"^```(?:json)?\s*\n?", "", content)
            content = re.sub(r"\n?\s*```\s*$", "", content)

            # Try to parse JSON from response
            json_match: re.Match[str] | None = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "approved": result.get("approved", False),
                    "score": float(result.get("score", 0.5)),
                    "feedback": result.get("feedback", ""),
                }

            logger.warning("LLM critique returned no JSON object")
            return {
                "approved": False,
                "score": 0.0,
                "feedback": "Critique failed — LLM returned no parseable JSON",
            }
        except Exception as exc:
            logger.error(f"LLM critique failed: {exc}")
            return {
                "approved": False,
                "score": 0.0,
                "feedback": f"Critique failed — LLM error: {exc}",
            }
