"""
Deep Agent node for complex reasoning tasks in LangGraph v3 workflows.

This module provides a node that uses the deepagents library to perform
sophisticated multi-step reasoning with tool calling capabilities.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List

# Suppress Pydantic warnings about typing.NotRequired from deepagents/LangGraph
warnings.filterwarnings(  # noqa: E402
    "ignore",
    message="typing.NotRequired is not a Python type",
    category=UserWarning,
    module="pydantic._internal._generate_schema"
)

from deepagents import create_deep_agent  # noqa: E402
from langchain.chat_models import init_chat_model  # noqa: E402
from langchain_core.messages import BaseMessage, HumanMessage  # noqa: E402
from langchain_core.tools import StructuredTool  # noqa: E402
from langgraph.graph.state import CompiledStateGraph  # noqa: E402
from langgraph.types import RunnableConfig  # noqa: E402
from tenacity import (  # noqa: E402
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from graph_kb_api.context import AppContext  # noqa: E402
from graph_kb_api.flows.v3.models.node_models import (  # noqa: E402
    NodeExecutionResult,
)
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3  # noqa: E402
from graph_kb_api.flows.v3.state.ask_code import AskCodeState  # noqa: E402
from graph_kb_api.flows.v3.utils.deep_agent_display import DeepAgentProgressDisplay  # noqa: E402
from graph_kb_api.flows.v3.utils.progress_queue import ProgressEvent, ProgressQueue  # noqa: E402
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator  # noqa: E402
from graph_kb_api.graph_kb.prompts.prompt_manager import GraphKBPromptManager  # noqa: E402
from graph_kb_api.utils.enhanced_logger import EnhancedLogger  # noqa: E402

logger = EnhancedLogger(__name__)


class DeepAgentNode(BaseWorkflowNodeV3):
    """
    Node that executes a deep agent for complex reasoning tasks.

    This node uses the deepagents library to perform sophisticated multi-step
    reasoning with access to all available code analysis tools. The agent can
    iteratively call tools, reason about the results, and provide comprehensive
    answers to complex code questions.
    """

    agent: CompiledStateGraph
    tools: List[StructuredTool]
    timeout_seconds: int
    max_retries: int
    prompt_manager = GraphKBPromptManager()

    def __init__(
        self,
        timeout_seconds: int = 600,
        max_retries: int = 3,
        tools: List = None,
        app_context: AppContext = None
    ):
        """
        Initialize the deep agent node with tools.

        Args:
            timeout_seconds: Timeout in seconds for each agent invocation attempt (default: 600 = 10 minutes)
            max_retries: Maximum number of retry attempts for transient failures (default: 3)
            tools: List of tools to provide to the agent (required - should be provided by workflow engine)
            app_context: Application context for accessing settings (required for model configuration)
        """
        super().__init__("deep_agent")

        if tools is None:
            raise ValueError("Tools must be provided to DeepAgentNode. Use workflow engine's _initialize_tools().")

        if app_context is None:
            raise ValueError("app_context must be provided to DeepAgentNode for model configuration.")

        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.tools = tools

        # Store model name from settings
        self.model_name = app_context.settings.openai_model

        # Load system prompt using GraphKBPromptManager
        system_prompt = self.prompt_manager.get_system_prompt()

        # Initialize LLM Model with configuration from app_context.settings
        llm_model = init_chat_model(
            model=app_context.settings.openai_model,
            max_tokens=app_context.settings.llm_max_output_tokens,
            temperature=app_context.settings.llm_temperature
        )

        # Create the deep agent with tools and system prompt
        self.agent = create_deep_agent(
            tools=self.tools,
            system_prompt=system_prompt,
            model=llm_model
        )

        logger.info(
            "Deep agent initialized",
            data={
                'model': self.model_name,
                'tool_count': len(self.tools),
                'timeout_seconds': self.timeout_seconds,
                'max_retries': self.max_retries
            }
        )

    async def _call_agent_with_retry(self, messages: List[BaseMessage], config: RunnableConfig) -> Dict[str, Any]:
        """
        Call deep agent with retry logic using tenacity.

        Uses exponential backoff with jitter to handle transient failures,
        rate limiting, and network issues gracefully.

        Args:
            messages: List of messages to send to agent
            config: Configuration for agent execution

        Returns:
            Agent response dictionary

        Raises:
            Exception: If all retry attempts fail
        """
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError, OSError)),
            before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
            reraise=True
        )
        async def _invoke_with_timeout() -> Dict[str, Any]:
            """Inner function with retry decorator."""
            return await asyncio.wait_for(
                self.agent.ainvoke(
                    {"messages": messages},
                    config=config
                ),
                timeout=self.timeout_seconds
            )

        return await _invoke_with_timeout()

    async def _execute_async(
        self,
        state: AskCodeState,
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute the deep agent node with streaming progress updates.

        Args:
            state: Current workflow state containing user query and context
            services: Injected services

        Returns:
            NodeExecutionResult with agent response and token usage
        """
        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            # Get user query from state (use refined_question if available, otherwise original_question)
            user_query = state.get('refined_question') or state.get('original_question', '')
            repo_id = state.get('repo_id', 'unknown')

            # Get progress queue for SSE streaming (optional)
            progress_queue: ProgressQueue | None = services.get("progress_queue")

            if not user_query:
                return NodeExecutionResult.error(
                    "No user query provided",
                    metadata={'node_type': self.node_name, 'error_type': 'missing_input'}
                )

            logger.info(
                "Executing deep agent with streaming",
                data={
                    'repo_id': repo_id,
                    'query_length': len(user_query)
                }
            )

            # Build messages for agent - just the user query
            # The agent will use search_code tool when it needs semantic search
            messages: List[BaseMessage] = [
                HumanMessage(content=f"Repository: {repo_id}\n\nQuestion: {user_query}")
            ]

            # Create config with repo_id for tools
            agent_config: RunnableConfig = {
                "configurable": {
                    "repo_id": repo_id
                }
            }

            # Emit initial progress
            if progress_queue:
                await progress_queue.emit(ProgressEvent(
                    step="deep_agent_init",
                    phase="Deep Agent Analysis",
                    progress_percent=10.0,
                    message="Initializing deep agent analysis",
                    details={"repo_id": repo_id},
                ))

            step_count = 0
            agent_messages = []
            estimated_tokens = 0

            try:
                # Stream agent execution with "updates" mode
                # Note: deepagents uses middleware that may emit updates with different structures

                async for chunk in self.agent.astream(
                    {"messages": messages},
                    config=agent_config,
                    stream_mode="updates"  # Track state updates
                ):
                    step_count += 1

                    # chunk should be a dict of {node_name: state_update}
                    # where state_update is typically a dict, but middleware may vary
                    if not isinstance(chunk, dict):
                        logger.warning(f"Unexpected chunk type: {type(chunk)}, skipping")
                        continue

                    for node_name, state_update in chunk.items():
                        # Log the step
                        logger.info(
                            f"Agent step: {node_name}",
                            data={
                                'step': step_count,
                                'update_type': type(state_update).__name__,
                                'has_messages': isinstance(state_update, dict) and 'messages' in state_update
                            }
                        )

                        # Update progress message (returns None if node should be skipped)
                        try:
                            progress_content = DeepAgentProgressDisplay.format_progress_update(
                                node_name,
                                step_count,
                                state_update
                            )

                            # Only emit if we got content (not skipped)
                            if progress_content and progress_queue:
                                progress_percent = min(10.0 + (step_count / 20) * 80, 90.0)
                                await progress_queue.emit(ProgressEvent(
                                    step="deep_agent_step",
                                    phase="Deep Agent Analysis",
                                    progress_percent=progress_percent,
                                    message=progress_content,
                                    details={
                                        "repo_id": repo_id,
                                        "step": step_count,
                                        "node_name": node_name,
                                    },
                                ))

                        except Exception as update_error:
                            logger.warning(f"Failed to update progress message: {update_error}")

                        # Track messages for final response
                        # State update should be a dict with the state changes
                        if isinstance(state_update, dict):
                            if 'messages' in state_update:
                                new_messages = state_update['messages']
                                if isinstance(new_messages, list):
                                    agent_messages.extend(new_messages)
                                else:
                                    agent_messages.append(new_messages)
                        else:
                            # If state_update is not a dict, it might be the actual state
                            # This can happen with certain middleware configurations
                            logger.debug(f"Non-dict state_update from {node_name}: {type(state_update)}")

                # Get final response
                if not agent_messages:
                    return NodeExecutionResult.error(
                        "Agent returned no messages",
                        metadata={'node_type': self.node_name, 'error_type': 'empty_response'}
                    )

                # Get the final message (agent's response)
                final_message: BaseMessage = agent_messages[-1]
                response_content: str = (
                    final_message.content
                    if hasattr(final_message, 'content')
                    else str(final_message)
                )

                # Estimate token usage using proper tokenization
                token_estimator = get_token_estimator()
                estimated_tokens = token_estimator.estimate_messages_tokens(messages + agent_messages)

                # Update progress to show completion with tool summary
                completion_summary = DeepAgentProgressDisplay.format_completion_summary(
                    step_count=step_count,
                    estimated_tokens=estimated_tokens,
                    agent_messages=agent_messages
                )

                # Emit completion progress
                if progress_queue:
                    await progress_queue.emit(ProgressEvent(
                        step="deep_agent_complete",
                        phase="Deep Agent Complete",
                        progress_percent=100.0,
                        message=completion_summary,
                        details={
                            "repo_id": repo_id,
                            "steps": step_count,
                            "estimated_tokens": estimated_tokens,
                        },
                    ))

                logger.info(
                    "Deep agent execution completed",
                    data={
                        'steps': step_count,
                        'estimated_tokens': estimated_tokens,
                        'response_length': len(response_content)
                    }
                )

                return NodeExecutionResult.success(
                    output={
                        'final_output': response_content,  # PresentToUserNode expects final_output
                        'agent_response': response_content,
                        'agent_messages': agent_messages,
                        'status': 'completed',
                        'steps_executed': step_count
                    },
                    tokens_used=estimated_tokens,
                    metadata={
                        'node_type': self.node_name,
                        'tool_count': len(self.tools),
                        'steps': step_count
                    }
                )

            except asyncio.TimeoutError as e:
                if progress_queue:
                    await progress_queue.emit(ProgressEvent(
                        step="deep_agent_error",
                        phase="Deep Agent Error",
                        progress_percent=0.0,
                        message=f"Execution exceeded {self.timeout_seconds}s timeout",
                        details={"repo_id": repo_id, "error_type": "timeout"},
                    ))
                logger.error(f"Deep agent timed out after {self.timeout_seconds}s")
                return NodeExecutionResult.error(
                    f"Deep agent timed out: {str(e)}",
                    metadata={'node_type': self.node_name, 'error_type': 'timeout'}
                )

            except (ConnectionError, OSError) as e:
                if progress_queue:
                    await progress_queue.emit(ProgressEvent(
                        step="deep_agent_error",
                        phase="Deep Agent Connection Error",
                        progress_percent=0.0,
                        message=f"Connection error: {str(e)}",
                        details={"repo_id": repo_id, "error_type": "connection_error"},
                    ))
                logger.error(
                    "Deep agent call failed after retries",
                    data={
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                )
                return NodeExecutionResult.error(
                    f"Deep agent call failed after retries: {str(e)}",
                    metadata={
                        'node_type': self.node_name,
                        'error_type': 'agent_retry_exhausted'
                    }
                )

            except Exception as e:
                if progress_queue:
                    await progress_queue.emit(ProgressEvent(
                        step="deep_agent_error",
                        phase="Deep Agent Error",
                        progress_percent=0.0,
                        message=f"Agent error: {str(e)}",
                        details={"repo_id": repo_id, "error_type": type(e).__name__},
                    ))
                logger.error(
                    "Deep agent call failed with non-retryable error",
                    data={
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                )
                return NodeExecutionResult.error(
                    f"Deep agent call failed: {str(e)}",
                    metadata={
                        'node_type': self.node_name,
                        'error_type': 'agent_error'
                    }
                )

        except Exception as e:
            logger.error(
                f"DeepAgentNode execution failed: {e}",
                data={
                    'node_type': self.node_name,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
            return NodeExecutionResult.error(
                f"Deep agent node failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
