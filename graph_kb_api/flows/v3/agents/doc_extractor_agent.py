"""
Document extractor agent for the multi-agent feature spec workflow.

Extracts and synthesizes information from supplementary documents
(OpenAPI specs, PRDs, existing docs). Reports confidence score with
each draft.
"""

from typing import Any, Dict, Mapping

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask, doc_extractor_capability
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.agent_helpers import build_prompt, compute_confidence

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("doc_extractor")


class DocExtractorAgent(BaseAgent):
    """Extracts relevant info from supplementary documents with confidence scoring.

    Extends BaseAgent with AgentCapability for document extraction tasks.
    Uses tools: get_file_content, search_code.
    """

    def __init__(self) -> None:
        pass

    @property
    def capability(self) -> AgentCapability:
        return doc_extractor_capability(system_prompt=_SYSTEM_PROMPT)

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute document extraction task and return draft with confidence score.

        Returns:
            Dict with:
            - agent_draft: str — the generated section content
            - confidence_score: float 0.0-1.0
            - confidence_rationale: str — explanation of confidence level
        """
        agent_context: Dict[str, Any] = state.get("agent_context", {}) or {}
        user_prompt: str = build_prompt(task, agent_context)
        confidence_score, confidence_rationale = compute_confidence(agent_context)

        if workflow_context is None:
            raise RuntimeError("DocExtractorAgent requires a WorkflowContext")
        agent_draft: str = await self._generate_draft(user_prompt, state, workflow_context)

        return {
            "agent_draft": agent_draft,
            "confidence_score": confidence_score,
            "confidence_rationale": confidence_rationale,
        }

    async def _generate_draft(
        self, user_prompt: str, state: Mapping[str, Any], workflow_context: WorkflowContext
    ) -> str:
        """Call the LLM to generate the draft. Gracefully handles missing LLM."""
        if workflow_context is None:
            return f"[Draft placeholder — no workflow_context provided]\n\n{user_prompt}"

        llm: LLMService = workflow_context.require_llm

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        all_tools = state.get("available_tools", [])
        assigned_tools: list[Any] = [
            t for t in all_tools if hasattr(t, "name") and t.name in self.capability.required_tools
        ]

        try:
            response = await llm.bind_tools(assigned_tools).ainvoke(messages)
            if hasattr(response, "content"):
                return response.content
            return str(response)
        except Exception as exc:
            return f"[Draft generation failed: {exc}]\n\n{user_prompt}"
