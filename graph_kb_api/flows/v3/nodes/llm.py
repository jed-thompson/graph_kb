"""
LLM agent node for LangGraph v3 agentic workflows.

This module provides a node that calls the LLM with tool binding,
handling token usage estimation and error recovery.
"""

import asyncio
import logging
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, SystemMessage
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import ServiceRegistry
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.utils.progress_queue import ProgressEvent, ProgressQueue
from graph_kb_api.flows.v3.utils.tool_display import ToolDisplayFormatter
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class LLMAgentNode(BaseWorkflowNodeV3):
    """
    LLM agent that decides whether to call tools or provide final answer.

    This node invokes the LLM with bound tools, allowing it to decide
    whether to call tools for more information or provide a final response.
    """

    def __init__(self, llm_with_tools, system_prompt: str):
        """
        Initialize the LLM agent node.

        Args:
            llm_with_tools: LLM instance with tools bound via bind_tools()
            system_prompt: System prompt to guide the agent's behavior
        """
        super().__init__("llm_agent")
        self.llm_with_tools = llm_with_tools
        self.system_prompt = system_prompt

    async def _call_llm_with_retry(self, messages: List) -> AIMessage:
        """
        Call LLM with retry logic using tenacity.

        Uses exponential backoff with jitter to handle transient failures,
        rate limiting, and network issues gracefully.

        Args:
            messages: List of messages to send to LLM

        Returns:
            AIMessage response from LLM

        Raises:
            Exception: If all retry attempts fail
        """

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError, OSError)),
            before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
            reraise=True,
        )
        async def _invoke_with_timeout():
            """Inner function with retry decorator."""
            return await asyncio.wait_for(
                self.llm_with_tools.ainvoke(messages),
                timeout=300,  # 5 minute timeout per attempt
            )

        return await _invoke_with_timeout()

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Execute LLM agent to decide next action.

        Args:
            state: Current workflow state containing conversation messages
            services: Injected services (not used directly)

        Returns:
            NodeExecutionResult with LLM response and token usage
        """
        # Session ID set by _setup_execution_context

        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            messages = state.get("messages", [])
            repo_id = state.get("repo_id", "unknown")
            iteration = state.get("agent_iterations", 0)

            # Get progress queue for SSE streaming (optional)
            progress_queue: ProgressQueue | None = services.get("progress_queue")

            # Build message list with system prompt and conversation history
            full_messages = [SystemMessage(content=self.system_prompt), *messages]

            logger.info(
                "Calling LLM agent",
                data={
                    "repo_id": state.get("repo_id"),
                    "iteration": iteration,
                    "message_count": len(full_messages),
                },
            )

            try:
                # Emit progress: LLM thinking
                if progress_queue and iteration == 0:
                    await progress_queue.emit(
                        ProgressEvent(
                            step="agent_analyzing",
                            phase="Agent analyzing",
                            progress_percent=75.0,
                            message="Agent analyzing context",
                            details={"repo_id": repo_id},
                        )
                    )

                # Call LLM with retry logic and timeout via tenacity
                response: AIMessage = await self._call_llm_with_retry(full_messages)

                # Estimate token usage
                # Simple word-based estimation (1 token ≈ 0.75 words)
                estimated_tokens = 0
                for msg in full_messages:
                    if hasattr(msg, "content"):
                        estimated_tokens += len(str(msg.content).split()) * 1.33

                if hasattr(response, "content"):
                    estimated_tokens += len(str(response.content).split()) * 1.33

                estimated_tokens = int(estimated_tokens)

                # Check if agent wants to call tools
                has_tool_calls: bool = hasattr(response, "tool_calls") and bool(response.tool_calls)

                logger.info(
                    "LLM agent call completed",
                    data={
                        "iteration": iteration,
                        "estimated_tokens": estimated_tokens,
                        "has_tool_calls": has_tool_calls,
                    },
                )

                # Prepare tool call history for state using utility
                new_tool_calls = []
                if has_tool_calls:
                    new_tool_calls = ToolDisplayFormatter.create_tool_call_records(
                        [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls],
                        iteration,
                    )

                # Emit progress based on whether tools will be called
                if progress_queue:
                    if has_tool_calls:
                        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
                        await progress_queue.emit(
                            ProgressEvent(
                                step="gathering_context",
                                phase="Gathering context",
                                progress_percent=80.0,
                                message=f"Calling tools: {', '.join(tool_names)}",
                                details={
                                    "repo_id": repo_id,
                                    "tool_calls": tool_names,
                                    "iteration": iteration,
                                },
                            )
                        )
                    elif iteration > 0:
                        await progress_queue.emit(
                            ProgressEvent(
                                step="building_response",
                                phase="Building final response",
                                progress_percent=90.0,
                                message="Agent building final response",
                                details={"repo_id": repo_id},
                            )
                        )

                # Return success with response
                return NodeExecutionResult.success(
                    output={
                        "messages": [response],
                        "agent_iterations": iteration + 1,
                        "tool_calls_history": new_tool_calls,  # Add pending tool calls to history
                    },
                    tokens_used=estimated_tokens,
                    metadata={"node_type": self.node_name, "iteration": iteration + 1},
                )

            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                # Retry-able errors that failed after all attempts
                logger.error(
                    "LLM agent call failed after retries",
                    data={"error_type": type(e).__name__, "error_message": str(e)},
                )

                return NodeExecutionResult.failure(
                    f"LLM agent call failed after retries: {str(e)}",
                    metadata={
                        "node_type": self.node_name,
                        "error_type": "llm_retry_exhausted",
                    },
                )

            except Exception as e:
                # Non-retryable errors
                logger.error(
                    "LLM agent call failed with non-retryable error",
                    data={"error_type": type(e).__name__, "error_message": str(e)},
                )

                return NodeExecutionResult.failure(
                    f"LLM agent call failed: {str(e)}",
                    metadata={"node_type": self.node_name, "error_type": "llm_error"},
                )

        except Exception as e:
            logger.error(
                f"LLMAgentNode execution failed: {e}",
                data={
                    "node_type": self.node_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return NodeExecutionResult.failure(
                f"LLM agent node failed: {str(e)}",
                metadata={"node_type": self.node_name, "error_type": type(e).__name__},
            )
