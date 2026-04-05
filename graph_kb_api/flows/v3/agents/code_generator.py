"""
Code generator agent implementation.

Specializes in code generation and refactoring tasks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.state import UnifiedSpecState

from langchain_core.messages import AIMessage

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.utils.agent_helpers import build_prompt
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class CodeGeneratorAgent(BaseAgent):
    """
    Agent specializing in code generation and refactoring.

    Capabilities:
    - Write new code
    - Refactor existing code
    - Generate function implementations
    - Create new classes or modules
    """

    _SYSTEM_PROMPT_TEMPLATE = get_agent_prompt_manager().get_prompt("code_generator")

    def __init__(self):
        pass

    @property
    def capability(self) -> AgentCapability:
        return AgentCapability(
            agent_type="code_generator",
            supported_tasks=["write_code", "refactor", "generate_function"],
            required_tools=["get_file_content", "get_related_files"],
            optional_tools=[],
            description="Writes and refactors code based on specifications",
            system_prompt=self._load_system_prompt(),
        )

    async def execute(
        self, task: AgentTask, state: UnifiedSpecState, workflow_context: WorkflowContext | None
    ) -> AgentResult:
        if not workflow_context:
            raise RuntimeError("CodeGeneratorAgent requires a workflow_context but none was provided.")

        try:
            agent_context: Dict[str, Any] = dict(state.get("agent_context", {}) or {})
            user_prompt: str = build_prompt(task, agent_context)
            logger.info(
                "CodeGeneratorAgent executing task",
                data={"task_description": task.get("description", "")[:100]},
            )

            messages = [
                {"role": "system", "content": self._load_system_prompt()},
                {"role": "user", "content": user_prompt},
            ]

            all_tools = state.get("available_tools", [])
            assigned_tools: list[Any] = [t for t in all_tools if t.name in self.capability.required_tools]

            llm: LLMService = workflow_context.require_llm

            response: AIMessage = await llm.bind_tools(assigned_tools).ainvoke(messages)

            # Extract content (handle str | list[str | dict] multi-modal content)
            output_content: str
            if hasattr(response, "content"):
                raw_content = response.content
                output_content = str(raw_content) if not isinstance(raw_content, str) else raw_content
            else:
                output_content = str(response)

            # Estimate token usage using tiktoken
            estimated_tokens: int = get_token_estimator().count_tokens(output_content)

            logger.info(
                "CodeGeneratorAgent execution completed",
                data={
                    "output_length": len(output_content),
                    "estimated_tokens": estimated_tokens,
                    "tools_used": [t.name for t in assigned_tools],
                },
            )

            return AgentResult(
                output=output_content,
                tokens=estimated_tokens,
                agent_type="code_generator",
            )

        except Exception as e:
            logger.error(f"CodeGeneratorAgent execution failed: {e}", exc_info=True)
            return AgentResult(
                output=f"Generation failed: {str(e)}",
                tokens=0,
                agent_type="code_generator",
            )

    def _load_system_prompt(self) -> str:
        # Load from prompt manager
        return self._SYSTEM_PROMPT_TEMPLATE
