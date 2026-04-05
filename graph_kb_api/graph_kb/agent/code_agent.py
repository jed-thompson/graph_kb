"""Code-aware agent using LangChain's create_agent.

This module provides an agent that can use Graph KB tools to explore
and answer questions about indexed codebases.
"""
# import chainlit as cl (Removed to avoid hard dependency)
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..tools import ToolRegistry

logger = EnhancedLogger(__name__)

# Path to the prompts directory
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class AgentResponse:
    """Response from the code agent."""

    success: bool
    answer: str
    tool_calls: List[Dict[str, Any]]
    error: Optional[str] = None


class CodeAgent:
    """Agent for code-aware Q&A using LangGraph agent.

    This agent wraps the Graph KB tools and provides an automatic
    tool execution loop for answering code questions.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tool_registry: ToolRegistry,
        system_prompt: str,
        max_iterations: int = 10,
        verbose: bool = False,
    ):
        """Initialize the CodeAgent.

        Args:
            llm: The LangChain chat model to use.
            tool_registry: Registry containing Graph KB tools.
            system_prompt: System prompt for the agent.
            max_iterations: Maximum tool call iterations.
            verbose: Whether to log verbose output.
        """
        self._llm = llm
        self._tool_registry = tool_registry
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._verbose = verbose

        # Convert registry tools to LangChain tools
        self._langchain_tools = self._create_langchain_tools()

        # Create the agent graph
        self._agent = self._create_agent()

    def _create_langchain_tools(self) -> List[StructuredTool]:
        """Convert ToolRegistry tools to LangChain StructuredTools.

        Returns:
            List of LangChain StructuredTool instances.
        """
        tools = []

        for tool_name in self._tool_registry.list_tools():
            tool_def = self._tool_registry.get_tool(tool_name)
            if tool_def is None:
                continue

            # Create a wrapper function that calls the registry
            def make_tool_func(name: str, handler: Callable) -> Callable:
                def tool_func(**kwargs) -> str:
                    try:
                        result = handler(**kwargs)
                        # Convert dataclass results to string
                        if hasattr(result, '__dataclass_fields__'):
                            return self._format_tool_result(result)
                        return str(result)
                    except Exception as e:
                        logger.error(f"Tool {name} failed: {e}")
                        return f"Error: {str(e)}"
                return tool_func

            # Build the tool
            langchain_tool = StructuredTool.from_function(
                func=make_tool_func(tool_def.name, tool_def.handler),
                name=tool_def.name,
                description=tool_def.description,
                args_schema=self._schema_to_pydantic(tool_def.name, tool_def.schema),
            )
            tools.append(langchain_tool)
            logger.debug(f"Created LangChain tool: {tool_def.name}")

        return tools

    def _schema_to_pydantic(self, name: str, schema: Dict[str, Any]):
        """Convert JSON schema to Pydantic model for tool args.

        Args:
            name: Tool name for the model.
            schema: JSON schema dict.

        Returns:
            Pydantic model class.
        """
        from typing import Optional as Opt

        from pydantic import Field, create_model

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        fields = {}
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "string")
            description = prop_schema.get("description", "")
            default = prop_schema.get("default")

            # Map JSON schema types to Python types
            type_map = {
                "string": str,
                "integer": int,
                "number": float,
                "boolean": bool,
            }
            python_type = type_map.get(prop_type, str)

            if prop_name in required:
                fields[prop_name] = (python_type, Field(description=description))
            else:
                fields[prop_name] = (
                    Opt[python_type],
                    Field(default=default, description=description)
                )

        return create_model(f"{name}Args", **fields)

    def _format_tool_result(self, result: Any) -> str:
        """Format a tool result dataclass to string.

        Args:
            result: The tool result (usually a dataclass).

        Returns:
            Formatted string representation.
        """
        if hasattr(result, 'success') and not result.success:
            error = getattr(result, 'error', 'Unknown error')
            return f"Error: {error}"

        # Handle SearchResult
        if hasattr(result, 'chunks'):
            chunks = result.chunks
            if not chunks:
                return "No results found."

            output = []
            for chunk in chunks[:10]:  # Limit to 10 results
                if chunk.get("type") == "code":
                    output.append(
                        f"File: {chunk.get('file_path', 'unknown')}\n"
                        f"Lines: {chunk.get('start_line', '?')}-{chunk.get('end_line', '?')}\n"
                        f"Symbol: {chunk.get('symbol', 'N/A')}\n"
                        f"```\n{chunk.get('content', '')[:1000]}\n```\n"
                    )
            return "\n---\n".join(output) if output else "No code results."

        # Handle SnippetResult
        if hasattr(result, 'content') and hasattr(result, 'file_path'):
            return (
                f"File: {result.file_path} "
                f"(lines {result.start_line}-{result.end_line})\n"
                f"```\n{result.content}\n```"
            )

        # Handle FlowResult
        if hasattr(result, 'path') and hasattr(result, 'description'):
            if result.description:
                return result.description
            return "No path found."

        # Handle ArchitectureResult
        if hasattr(result, 'modules'):
            if not result.modules:
                return "No modules found."

            output = ["Modules:"]
            for mod in result.modules[:20]:
                output.append(f"  - {mod.get('name', 'unknown')}")
            return "\n".join(output)

        # Handle FindEntryPointsResult
        if hasattr(result, 'entry_points'):
            if not result.entry_points:
                return "No entry points found."

            output = [f"Found {len(result.entry_points)} entry points:"]
            for ep in result.entry_points[:15]:
                line = f"  - {ep.get('name', 'unknown')} ({ep.get('type', '?')}) in {ep.get('file_path', '?')}"
                if ep.get('http_method'):
                    line += f" [{ep['http_method']}]"
                output.append(line)
            if len(result.entry_points) > 15:
                output.append(f"  ... and {len(result.entry_points) - 15} more")
            return "\n".join(output)

        # Handle SymbolReferencesResult
        if hasattr(result, 'references') and hasattr(result, 'direction'):
            if not result.references:
                return f"No {result.direction} found for {result.symbol_name}"

            output = [f"{result.direction.title()} of {result.symbol_name} ({len(result.references)}):"]
            for ref in result.references[:15]:
                output.append(f"  - {ref.get('name', '?')} ({ref.get('kind', '?')}) in {ref.get('file_path', '?')}")
            if len(result.references) > 15:
                output.append(f"  ... and {len(result.references) - 15} more")
            return "\n".join(output)

        # Handle TraceDataFlowResult
        if hasattr(result, 'steps') and hasattr(result, 'entry_point'):
            if not result.steps:
                return f"No data flow found from {result.entry_point}"

            output = [f"Data flow from {result.entry_point} ({len(result.steps)} steps):"]
            for step in result.steps[:20]:
                indent = "  " * step.get('depth', 0)
                output.append(f"{indent}- {step.get('symbol_name', '?')} [{step.get('step_type', '?')}] in {step.get('file_path', '?')}")
            if result.is_truncated:
                output.append(f"  (truncated at depth {result.max_depth_reached})")
            return "\n".join(output)

        # Handle ListFilesResult
        if hasattr(result, 'files') and hasattr(result, 'tree'):
            if not result.files:
                return "No files found."
            return f"Files ({len(result.files)}):\n{result.tree}"

        # Fallback: convert to string
        return str(result)

    def _create_agent(self):
        """Create the LangGraph agent.

        Returns:
            Compiled LangGraph agent.
        """
        # Create the agent with system prompt using new create_agent API
        # from langchain.agents (not langgraph.prebuilt)
        agent = create_agent(
            model=self._llm,
            tools=self._langchain_tools,
            system_prompt=self._system_prompt,
        )

        return agent

    def invoke(self, question: str, context: str = "") -> AgentResponse:
        """Invoke the agent synchronously.

        Args:
            question: The user's question.
            context: Additional context to include.

        Returns:
            AgentResponse with the answer and tool calls.
        """
        try:
            input_text = question
            if context:
                input_text = f"{context}\n\nQuestion: {question}"

            # Run the agent
            result = self._agent.invoke({
                "messages": [HumanMessage(content=input_text)]
            })

            # Extract answer and tool calls from messages
            answer, tool_calls = self._extract_response(result)

            return AgentResponse(
                success=True,
                answer=answer,
                tool_calls=tool_calls,
            )

        except Exception as e:
            logger.exception(f"Agent execution failed: {e}")
            return AgentResponse(
                success=False,
                answer="",
                tool_calls=[],
                error=str(e),
            )

    async def ainvoke(
        self,
        question: str,
        context: str = "",
        show_tool_calls: bool = False,
    ) -> AgentResponse:
        """Invoke the agent asynchronously.

        Args:
            question: The user's question.
            context: Additional context to include.
            show_tool_calls: If True, display tool calls in Chainlit UI.

        Returns:
            AgentResponse with the answer and tool calls.
        """
        try:
            input_text = question
            if context:
                input_text = f"{context}\n\nQuestion: {question}"

            if show_tool_calls:
                # Stream events to show tool calls in real-time
                return await self._ainvoke_with_streaming(input_text)
            else:
                # Run the agent asynchronously without streaming
                result = await self._agent.ainvoke({
                    "messages": [HumanMessage(content=input_text)]
                })

                # Extract answer and tool calls from messages
                answer, tool_calls = self._extract_response(result)

                return AgentResponse(
                    success=True,
                    answer=answer,
                    tool_calls=tool_calls,
                )

        except Exception as e:
            logger.exception(f"Agent execution failed: {e}")
            return AgentResponse(
                success=False,
                answer="",
                tool_calls=[],
                error=str(e),
            )

    async def _ainvoke_with_streaming(self, input_text: str) -> AgentResponse:
        """Invoke agent with streaming to show tool calls in Chainlit.

        Args:
            input_text: The input text for the agent.

        Returns:
            AgentResponse with the answer and tool calls.
        """
        try:
            import chainlit as cl
        except ImportError:
            # Chainlit not available, fall back to non-streaming
            logger.warning("Chainlit not available, falling back to non-streaming mode")
            result = await self._agent.ainvoke({
                "messages": [HumanMessage(content=input_text)]
            })
            answer, tool_calls = self._extract_response(result)
            return AgentResponse(success=True, answer=answer, tool_calls=tool_calls)

        tool_calls_list = []
        final_answer = ""
        current_step = None
        pending_tool_calls = {}  # Track tool calls by run_id

        try:
            # Stream events from the agent using v2 format
            async for event in self._agent.astream_events(
                {"messages": [HumanMessage(content=input_text)]},
                version="v2"  # Use v2 for newer LangGraph
            ):
                kind = event.get("event")
                run_id = event.get("run_id", "")
                name = event.get("name", "")

                # Debug logging for all events
                if self._verbose:
                    logger.debug(f"Stream event: {kind} | name={name} | run_id={run_id[:8] if run_id else 'N/A'}")

                # Tool call started - look for tool invocations
                if kind == "on_tool_start":
                    tool_name = name or event.get("data", {}).get("input", {}).get("name", "unknown_tool")
                    tool_input = event.get("data", {}).get("input", {})

                    logger.info(f"🔧 Tool started: {tool_name}")

                    # Create a Chainlit step for this tool call
                    try:
                        step_name = self._format_tool_name(tool_name)
                        current_step = cl.Step(name=f"🔧 {step_name}", type="tool")
                        await current_step.send()

                        # Show input parameters
                        input_summary = self._format_tool_input(tool_name, tool_input)
                        current_step.input = input_summary
                        await current_step.update()

                        # Track by run_id for matching end events
                        pending_tool_calls[run_id] = {
                            "step": current_step,
                            "name": tool_name,
                            "input": tool_input,
                        }
                    except Exception as step_error:
                        logger.warning(f"Failed to create Chainlit step: {step_error}")

                # Tool call completed
                elif kind == "on_tool_end":
                    tool_name = name or "unknown_tool"
                    tool_output = event.get("data", {}).get("output")

                    logger.info(f"✅ Tool completed: {tool_name}")

                    # Find matching step by run_id
                    if run_id in pending_tool_calls:
                        pending_call = pending_tool_calls.pop(run_id)
                        step = pending_call.get("step")
                        if step:
                            try:
                                output_summary = self._format_tool_output(tool_name, tool_output)
                                step.output = output_summary
                                await step.update()
                            except Exception as step_error:
                                logger.warning(f"Failed to update Chainlit step: {step_error}")

                        # Track tool call
                        tool_calls_list.append({
                            "tool": tool_name,
                            "input": pending_call.get("input", {}),
                            "output": tool_output,
                        })
                    elif current_step:
                        # Fallback: update current step if run_id matching failed
                        try:
                            output_summary = self._format_tool_output(tool_name, tool_output)
                            current_step.output = output_summary
                            await current_step.update()
                        except Exception as step_error:
                            logger.warning(f"Failed to update Chainlit step: {step_error}")

                        tool_calls_list.append({
                            "tool": tool_name,
                            "input": event.get("data", {}).get("input", {}),
                            "output": tool_output,
                        })


                # LLM response chunks - extract final answer
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        # Accumulate streamed content (this is the final answer being generated)
                        pass  # We'll get the full answer at the end

                # LLM response completed
                elif kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    if output:
                        # Handle different output formats
                        if hasattr(output, "content"):
                            content = output.content
                            # Only update if this looks like a final answer (not tool calls)
                            if content and not (hasattr(output, "tool_calls") and output.tool_calls):
                                final_answer = content
                        elif isinstance(output, dict):
                            messages = output.get("messages", [])
                            if messages:
                                last_msg = messages[-1]
                                if hasattr(last_msg, "content"):
                                    final_answer = last_msg.content

            # If we didn't get final answer from streaming, extract from final state
            if not final_answer:
                logger.debug("No final answer from streaming, invoking agent directly")
                result = await self._agent.ainvoke({
                    "messages": [HumanMessage(content=input_text)]
                })
                final_answer, _ = self._extract_response(result)

            return AgentResponse(
                success=True,
                answer=final_answer,
                tool_calls=tool_calls_list,
            )

        except Exception as e:
            logger.exception(f"Streaming agent execution failed: {e}")
            # Fall back to non-streaming
            result = await self._agent.ainvoke({
                "messages": [HumanMessage(content=input_text)]
            })
            answer, tool_calls = self._extract_response(result)
            return AgentResponse(success=True, answer=answer, tool_calls=tool_calls)

    def _format_tool_name(self, tool_name: str) -> str:
        """Format tool name for display.

        Args:
            tool_name: Raw tool name.

        Returns:
            Formatted display name.
        """
        # Convert snake_case to Title Case
        return tool_name.replace("_", " ").title()

    def _format_tool_input(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Format tool input for display.

        Args:
            tool_name: The tool name.
            tool_input: The tool input parameters.

        Returns:
            Formatted input string.
        """
        if not tool_input:
            return "No parameters"

        # Format key parameters based on tool type
        if tool_name == "search_repo":
            query = tool_input.get("query", "")
            max_results = tool_input.get("max_results", 10)
            return f"Query: `{query}`\nMax results: {max_results}"

        elif tool_name == "get_file_snippet":
            file_path = tool_input.get("file_path", "")
            start_line = tool_input.get("start_line", "")
            end_line = tool_input.get("end_line", "")
            return f"File: `{file_path}`\nLines: {start_line}-{end_line}"

        elif tool_name == "trace_data_flow":
            entry_point = tool_input.get("entry_point_name", "")
            max_depth = tool_input.get("max_depth", 10)
            return f"Entry point: `{entry_point}`\nMax depth: {max_depth}"

        elif tool_name == "get_symbol_references":
            symbol = tool_input.get("symbol_name", "")
            direction = tool_input.get("direction", "callers")
            return f"Symbol: `{symbol}`\nDirection: {direction}"

        else:
            # Generic formatting
            lines = []
            for key, value in tool_input.items():
                if isinstance(value, str) and len(value) > 50:
                    value = value[:47] + "..."
                lines.append(f"{key}: `{value}`")
            return "\n".join(lines[:5])  # Limit to 5 parameters

    def _format_tool_output(self, tool_name: str, tool_output: Any) -> str:
        """Format tool output for display.

        Args:
            tool_name: The tool name.
            tool_output: The tool output.

        Returns:
            Formatted output string.
        """
        if not tool_output:
            return "No output"

        output_str = str(tool_output)

        # Truncate long outputs
        if len(output_str) > 500:
            lines = output_str.split("\n")
            if len(lines) > 10:
                return "\n".join(lines[:10]) + f"\n... ({len(lines) - 10} more lines)"
            else:
                return output_str[:500] + "..."

        return output_str

    def _extract_response(self, result: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
        """Extract the final answer and tool calls from agent result.

        Args:
            result: The agent execution result.

        Returns:
            Tuple of (answer string, list of tool call dicts).
        """
        messages = result.get("messages", [])
        tool_calls = []
        answer = ""

        for msg in messages:
            # Extract tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "tool": tc.get("name", "unknown"),
                        "input": tc.get("args", {}),
                    })

            # Get the final AI message as the answer
            if hasattr(msg, 'content') and msg.type == "ai" and not hasattr(msg, 'tool_calls'):
                answer = msg.content
            elif hasattr(msg, 'content') and msg.type == "ai":
                # AI message with tool calls - check if it also has content
                if msg.content and not msg.tool_calls:
                    answer = msg.content

        # If no clean answer found, get the last AI message content
        if not answer:
            for msg in reversed(messages):
                if hasattr(msg, 'content') and msg.type == "ai" and msg.content:
                    answer = msg.content
                    break

        return answer, tool_calls


def create_code_agent(
    llm: BaseChatModel,
    tool_registry: ToolRegistry,
    system_prompt: Optional[str] = None,
    max_iterations: int = 10,
    verbose: bool = False,
) -> CodeAgent:
    """Factory function to create a CodeAgent.

    Args:
        llm: The LangChain chat model.
        tool_registry: Registry with Graph KB tools.
        system_prompt: Optional custom system prompt.
        max_iterations: Max tool call iterations.
        verbose: Enable verbose logging.

    Returns:
        Configured CodeAgent instance.
    """
    if system_prompt is None:
        system_prompt = _get_default_system_prompt()

    return CodeAgent(
        llm=llm,
        tool_registry=tool_registry,
        system_prompt=system_prompt,
        max_iterations=max_iterations,
        verbose=verbose,
    )


def _get_default_system_prompt() -> str:
    """Get the default system prompt for the code agent.

    Loads the prompt from the markdown file in the prompts directory.

    Returns:
        The system prompt content.
    """
    prompt_path = _PROMPTS_DIR / "code_agent_system_prompt.md"
    return prompt_path.read_text(encoding="utf-8")
