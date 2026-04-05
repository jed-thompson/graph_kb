"""
Code analyst agent implementation.

Specializes in code analysis tasks including pattern analysis,
dependency tracing, and code understanding.
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


class CodeAnalystAgent(BaseAgent):
    """
    Agent specializing in code analysis tasks.

    Capabilities:
    - Pattern analysis
    - Dependency tracing
    - Code understanding
    - Hotspot detection
    """

    _SYSTEM_PROMPT_TEMPLATE = get_agent_prompt_manager().get_prompt("code_analyst")

    def __init__(self):
        # Initialize without parameters for BaseAgent
        pass

    @property
    def capability(self) -> AgentCapability:
        """
        Return agent's capability description.
        """
        return AgentCapability(
            agent_type="code_analyst",
            supported_tasks=[
                "pattern_analysis",
                "dependency_tracing",
                "code_understanding",
                "hotspot_detection",
            ],
            required_tools=[
                "search_code",
                "get_symbol_info",
                "trace_call_chain",
                "get_file_content",
            ],
            optional_tools=[
                "execute_cypher_query",
                "get_related_files",
            ],
            description="Analyzes code patterns, traces dependencies, and understands code structure",
            system_prompt=self._load_system_prompt(),
        )

    async def execute(
        self, task: AgentTask, state: UnifiedSpecState, workflow_context: WorkflowContext | None
    ) -> AgentResult:
        """
        Execute code analysis task.

        Args:
            task: Task definition containing description and context
            state: Current workflow state (read-only)
            workflow_context: Application context with LLM and services

        Returns:
            AgentResult containing output, tokens, and optional error
        """
        if not workflow_context:
            raise RuntimeError("CodeAnalystAgent requires a workflow_context but none was provided.")

        try:
            agent_context: Dict[str, Any] = dict(state.get("agent_context", {}) or {})
            user_prompt: str = build_prompt(task, agent_context)
            logger.info(
                "CodeAnalystAgent executing task",
                data={"task_description": task.get("description", "")[:100]},
            )

            # Prepare messages for LLM
            messages = [
                {"role": "system", "content": self._load_system_prompt()},
                {"role": "user", "content": user_prompt},
            ]

            # Get available tools from state or services
            all_tools = state.get("available_tools", [])
            assigned_tools = [
                t
                for t in all_tools
                if t.name in self.capability.required_tools or t.name in self.capability.optional_tools
            ]

            # Get LLM from workflow_context
            llm: LLMService = workflow_context.require_llm

            # Bind tools to LLM if available
            llm_with_tools = llm.bind_tools(assigned_tools) if assigned_tools else llm

            # Invoke LLM
            response: AIMessage = await llm_with_tools.ainvoke(messages)

            # Extract content (handle str | list[str | dict] multimodal content)
            output_content: str
            if hasattr(response, "content"):
                raw_content = response.content
                output_content = str(raw_content) if not isinstance(raw_content, str) else raw_content
            else:
                output_content = str(response)

            # Estimate token usage using tiktoken
            estimated_tokens: int = get_token_estimator().count_tokens(output_content)

            logger.info(
                "CodeAnalystAgent execution completed",
                data={
                    "output_length": len(output_content),
                    "estimated_tokens": estimated_tokens,
                    "tools_used": [t.name for t in assigned_tools],
                },
            )

            return AgentResult(
                output=output_content,
                tokens=estimated_tokens,
                agent_type="code_analyst",
            )

        except Exception as e:
            logger.error(f"CodeAnalystAgent execution failed: {e}", exc_info=True)
            return AgentResult(
                output=f"Analysis failed: {str(e)}",
                tokens=0,
                agent_type="code_analyst",
            )

    def _load_system_prompt(self) -> str:
        """
        Load system prompt from template or default.

        Returns:
            System prompt string
        """
        # Load from prompt manager
        return self._SYSTEM_PROMPT_TEMPLATE
