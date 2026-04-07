"""
Tool execution node for LangGraph v3 agentic workflows.

This module provides a node that executes tools requested by LLM agents
with comprehensive logging and error handling.
"""

import asyncio
from typing import Any, Dict, List

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.state.ask_code import AskCodeState
from graph_kb_api.flows.v3.utils.progress_queue import ProgressEvent, ProgressQueue
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.utils.timeout_config import TimeoutConfig

logger = EnhancedLogger(__name__)


class AgenticToolNode(BaseWorkflowNodeV3):
    """
    Executes tools requested by LLM agent with logging.

    This node wraps LangGraph's ToolNode to add comprehensive logging
    with EnhancedLogger, tracking tool calls and results in state.
    """

    def __init__(self, tools: List):
        """
        Initialize the agentic tool node.

        Args:
            tools: List of LangChain tools available for execution
        """
        super().__init__("agentic_tool")
        self.tool_node = ToolNode(tools)
        self.tools_by_name = {tool.name: tool for tool in tools}


    async def _execute_async(
        self,
        state: AskCodeState,
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute tools requested by the LLM agent.

        Args:
            state: Current workflow state containing messages with tool calls
            services: Injected services (not used directly, but available)

        Returns:
            NodeExecutionResult with tool results and updated state
        """
        # Session ID set by _setup_execution_context

        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            messages = state.get('messages', [])
            repo_id = state.get('repo_id', 'unknown')

            # Get progress queue for SSE streaming (optional)
            progress_queue: ProgressQueue | None = services.get("progress_queue")

            if not messages:
                return NodeExecutionResult.error(
                    "No messages in state",
                    metadata={'node_type': self.node_name}
                )

            last_message = messages[-1]

            # Check if last message has tool calls
            if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
                return NodeExecutionResult.error(
                    "No tool calls in last message",
                    metadata={'node_type': self.node_name}
                )

            tool_results = []
            tool_calls_made = []
            tool_calls_completed = []  # Track completed tool calls for state update

            # Execute each tool call with keepalive support
            for idx, tool_call in enumerate(last_message.tool_calls):
                tool_name = tool_call['name']
                tool_args = tool_call['args']
                tool_call_id = tool_call['id']

                with logger.timer(f"tool_call:{tool_name}"):
                    try:
                        logger.info(
                            f"Executing tool: {tool_name}",
                            data={
                                'tool_name': tool_name,
                                'repo_id': state.get('repo_id'),
                                'iteration': state.get('agent_iterations', 0),
                                'input_args': tool_args
                            }
                        )

                        # Get tool and invoke it
                        tool = self.tools_by_name.get(tool_name)
                        if not tool:
                            error_msg = f"Tool '{tool_name}' not found"
                            logger.error(error_msg)
                            tool_results.append(
                                ToolMessage(
                                    content=error_msg,
                                    tool_call_id=tool_call_id
                                )
                            )
                            continue

                        # Execute tool with keepalive for long-running operations
                        result = await self._execute_tool_with_keepalive(
                            tool=tool,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            progress_queue=progress_queue,
                            repo_id=repo_id,
                            idx=idx,
                            total_tools=len(last_message.tool_calls)
                        )

                        # Create tool message
                        tool_results.append(
                            ToolMessage(
                                content=str(result),
                                tool_call_id=tool_call_id
                            )
                        )

                        # Track tool call
                        tool_calls_made.append({
                            'iteration': state.get('agent_iterations', 0),
                            'tool': tool_name,
                            'args': tool_args,
                            'result_summary': str(result)
                        })

                        # Mark as completed for state update
                        tool_calls_completed.append({
                            'iteration': state.get('agent_iterations', 0),
                            'tool_name': tool_name,
                            'args': tool_args,
                            'status': 'completed'
                        })

                        logger.info(
                            f"Tool {tool_name} completed successfully",
                            data={
                                'tool_name': tool_name,
                                'result_length': len(str(result))
                            }
                        )

                    except Exception as e:
                        logger.error(
                            f"Tool {tool_name} failed: {e}",
                            data={
                                'tool_name': tool_name,
                                'error_type': type(e).__name__,
                                'error_message': str(e)
                            }
                        )
                        tool_results.append(
                            ToolMessage(
                                content=f"Error: {str(e)}",
                                tool_call_id=tool_call_id
                            )
                        )

                        # Mark as failed for state update
                        tool_calls_completed.append({
                            'iteration': state.get('agent_iterations', 0),
                            'tool_name': tool_name,
                            'args': tool_args,
                            'status': 'failed',
                            'error': str(e)
                        })

            # Emit progress: tools completed
            if progress_queue and tool_calls_completed:
                completed_names = [tc['tool_name'] for tc in tool_calls_completed]
                await progress_queue.emit(ProgressEvent(
                    step="analyzing_results",
                    phase="Analyzing results",
                    progress_percent=85.0,
                    message=f"Completed {len(tool_calls_completed)} tool(s): {', '.join(completed_names)}",
                    details={"repo_id": repo_id, "tools_completed": completed_names},
                ))

            # Return success with tool results
            return NodeExecutionResult.success(
                output={
                    'messages': tool_results,
                    'tool_calls_made': tool_calls_made,
                    'tool_calls_history': tool_calls_completed  # Update history with completed status
                },
                metadata={
                    'node_type': self.node_name,
                    'tools_executed': len(tool_results)
                }
            )

        except Exception as e:
            logger.error(
                f"AgenticToolNode execution failed: {e}",
                data={
                    'node_type': self.node_name,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
            return NodeExecutionResult.error(
                f"Tool execution failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    async def _execute_tool_with_keepalive(
        self,
        tool: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
        progress_queue: ProgressQueue | None,
        repo_id: str,
        idx: int,
        total_tools: int
    ) -> Any:
        """
        Execute a tool with keepalive updates to prevent WebSocket timeout.

        This method wraps tool execution with a keepalive task that periodically
        emits progress events to prevent the WebSocket from timing out during
        long-running tool operations (especially search_code which can take 30-75s).

        Args:
            tool: The tool to execute
            tool_name: Name of the tool
            tool_args: Arguments for the tool
            progress_queue: Progress queue for SSE streaming
            repo_id: Repository ID
            idx: Current tool index
            total_tools: Total number of tools being executed

        Returns:
            Tool execution result
        """
        # Track last update time for keepalive
        last_update = asyncio.get_event_loop().time()
        keepalive_interval = TimeoutConfig.get_websocket_keepalive_interval()

        # Tool execution task
        async def tool_task():
            if hasattr(tool, 'ainvoke'):
                return await tool.ainvoke(tool_args)
            else:
                # Run sync tool in executor to avoid blocking
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, tool.invoke, tool_args)

        # Keepalive task to prevent WebSocket timeout
        async def keepalive_task():
            nonlocal last_update
            while True:
                await asyncio.sleep(5)  # Check every 5 seconds
                current_time = asyncio.get_event_loop().time()

                if current_time - last_update > keepalive_interval:
                    elapsed = int(current_time - last_update)

                    if progress_queue:
                        await progress_queue.emit(ProgressEvent(
                            step="tool_execution_keepalive",
                            phase="Executing tool",
                            progress_percent=80.0,
                            message=f"Still running: {tool_name} ({idx + 1}/{total_tools})",
                            details={
                                "repo_id": repo_id,
                                "tool_name": tool_name,
                                "tool_index": idx + 1,
                                "total_tools": total_tools,
                                "elapsed_seconds": elapsed,
                            },
                        ))

                    last_update = current_time

        # Run both tasks concurrently
        tool_task_obj = asyncio.create_task(tool_task())
        keepalive_task_obj = asyncio.create_task(keepalive_task())

        try:
            # Wait for tool execution with timeout
            timeout_seconds = TimeoutConfig.get_retrieval_timeout()  # Use same timeout as retrieval
            result = await asyncio.wait_for(tool_task_obj, timeout=timeout_seconds)
            keepalive_task_obj.cancel()
            return result
        except asyncio.TimeoutError:
            keepalive_task_obj.cancel()
            logger.error(f"Tool {tool_name} timed out after {timeout_seconds}s")
            raise TimeoutError(f"Tool execution timed out after {timeout_seconds}s")
        except Exception as e:
            keepalive_task_obj.cancel()
            raise e
