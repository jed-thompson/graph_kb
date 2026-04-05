"""
Display utilities for Deep Agent workflow progress.

This module provides centralized formatting logic for displaying Deep Agent
progress updates, following the same pattern as CodeAnalysisProgressDisplay
and ToolDisplayFormatter.

Key responsibilities:
- Filter out middleware steps (TodoListMiddleware, SummarizationMiddleware, etc.)
- Display meaningful agent progress (reasoning, tool calls, results)
- Extract and display todo list when available
- Consolidate duplicate steps to avoid noise
"""

from typing import Any, Dict, List, Optional


class DeepAgentProgressDisplay:
    """Formats Deep Agent progress updates for user-friendly display."""

    # Node name to user-friendly description mapping
    NODE_DESCRIPTIONS = {
        'agent': '🤔 Reasoning and planning',
        'tools': '🔧 Executing tools',
        'model': '💭 Generating response',
        '__start__': '🚀 Starting analysis',
        '__end__': '✅ Completing analysis'
    }

    # Tool name to user-friendly description mapping
    TOOL_DESCRIPTIONS = {
        'search_code': '🔍 Searching codebase',
        'read_file': '📄 Reading file',
        'get_file_content': '📄 Reading file',
        'ls': '📁 Listing directory',
        'grep': '🔎 Searching for pattern',
        'get_symbol_info': '🏷️ Getting symbol information',
        'write_file': '✍️ Writing file',
        'edit_file': '✏️ Editing file',
        'glob': '🔎 Finding files by pattern',
        'write_todos': '📝 Updating task list'
    }

    @classmethod
    def should_skip_node(cls, node_name: str) -> bool:
        """
        Determine if a node should be skipped from display.

        Args:
            node_name: Name of the node

        Returns:
            True if node should be skipped (middleware, internal nodes)
        """
        # Skip middleware nodes
        if 'Middleware' in node_name:
            return True

        # Skip internal LangGraph nodes
        if node_name.startswith('__') and node_name not in cls.NODE_DESCRIPTIONS:
            return True

        return False

    @classmethod
    def extract_todo_list(cls, state_update: Any) -> Optional[str]:
        """
        Extract todo list from state update if available.

        The TodoListMiddleware stores todos in the state. This method
        attempts to extract and format them for display.

        Args:
            state_update: State update from the agent

        Returns:
            Formatted todo list string, or None if not found
        """
        if not isinstance(state_update, dict):
            return None

        # Check for todos in various possible locations
        todos = None
        if 'todos' in state_update:
            todos = state_update['todos']
        elif 'todo_list' in state_update:
            todos = state_update['todo_list']

        if not todos:
            return None

        # Format the todo list
        if isinstance(todos, list):
            if not todos:
                return None

            todo_section = "**📝 Task List:**\n"
            for i, todo in enumerate(todos, 1):
                if isinstance(todo, dict):
                    task = todo.get('task', todo.get('description', str(todo)))
                    status = todo.get('status', 'pending')
                    if status == 'completed':
                        todo_section += f"{i}. ✅ ~~{task}~~\n"
                    else:
                        todo_section += f"{i}. ⬜ {task}\n"
                else:
                    todo_section += f"{i}. ⬜ {todo}\n"

            return todo_section + "\n"
        elif isinstance(todos, str):
            return f"**📝 Task List:**\n{todos}\n\n"

        return None

    @classmethod
    def extract_tool_calls_from_messages(cls, messages: List[Any]) -> List[Dict]:
        """
        Extract tool calls from messages.

        Args:
            messages: List of messages

        Returns:
            List of tool call dictionaries
        """
        tool_calls = []

        if not isinstance(messages, list):
            messages = [messages]

        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_calls.extend(msg.tool_calls)

        return tool_calls

    @classmethod
    def extract_tool_results_from_messages(cls, messages: List[Any]) -> List[Dict]:
        """
        Extract tool results from messages.

        Args:
            messages: List of messages

        Returns:
            List of tool result dictionaries with name and content
        """
        tool_results = []

        if not isinstance(messages, list):
            messages = [messages]

        for msg in messages:
            if hasattr(msg, 'name') and hasattr(msg, 'content'):
                tool_results.append({
                    'name': msg.name,
                    'content': msg.content
                })

        return tool_results

    @classmethod
    def format_progress_update(
        cls,
        node_name: str,
        step_count: int,
        state_update: Any
    ) -> Optional[str]:
        """
        Format a progress update message based on the agent's current step.

        This method:
        - Filters out middleware nodes
        - Extracts and displays todo lists
        - Shows tool calls and results
        - Displays agent reasoning

        Args:
            node_name: Name of the current node being executed
            step_count: Current step number
            state_update: State update from the agent (may be dict or other type)

        Returns:
            Formatted progress message, or None if node should be skipped
        """
        # Skip middleware and internal nodes
        if cls.should_skip_node(node_name):
            return None

        # Get node description
        description = cls.NODE_DESCRIPTIONS.get(
            node_name,
            f'⚙️ {node_name}'
        )

        # Build progress message
        progress = "🧠 **Deep Agent Analysis**\n\n"
        progress += f"**Step {step_count}:** {description}\n\n"

        # Check for todo list first
        todo_list = cls.extract_todo_list(state_update)
        if todo_list:
            progress += todo_list

        # Extract messages if available
        messages = []
        if isinstance(state_update, dict) and 'messages' in state_update:
            messages = state_update['messages']
            if not isinstance(messages, list):
                messages = [messages]

        # Extract and display tool calls
        tool_calls = cls.extract_tool_calls_from_messages(messages)
        if tool_calls:
            tool_section = cls._format_tool_calls(tool_calls)
            if tool_section:
                progress += tool_section

        # Extract and display tool results
        tool_results = cls.extract_tool_results_from_messages(messages)
        if tool_results:
            for result in tool_results:
                result_section = cls._format_tool_result(result['name'], result['content'])
                if result_section:
                    progress += result_section

        # Show agent reasoning if no tools
        if not tool_calls and not tool_results:
            for msg in messages:
                if hasattr(msg, 'content') and msg.content:
                    content_str = str(msg.content).strip()
                    if content_str and content_str != "[]" and len(content_str) > 0:
                        content_preview = content_str[:200]
                        if len(content_str) > 200:
                            content_preview += "..."
                        progress += f"💭 **Agent reasoning:**\n> {content_preview}\n\n"
                        break

        # If nothing meaningful to show, add context based on node type
        if not todo_list and not tool_calls and not tool_results and not any(hasattr(m, 'content') and m.content for m in messages):
            if node_name == 'agent':
                progress += "_Analyzing the question and planning approach..._\n"
            elif node_name == 'tools':
                progress += "_Executing tools..._\n"
            elif node_name == 'model':
                progress += "_Generating response..._\n"
            else:
                progress += "_Processing..._\n"

        return progress

    @classmethod
    def _format_tool_calls(cls, tool_calls: List[Dict]) -> str:
        """
        Format tool calls section.

        Args:
            tool_calls: List of tool call dictionaries

        Returns:
            Formatted tool calls section, or empty string if no valid calls
        """
        if not tool_calls:
            return ""

        section = "**🔧 Tools being called:**\n"

        for tool_call in tool_calls:
            tool_name = tool_call.get('name', 'unknown')
            tool_args = tool_call.get('args', {})

            tool_desc = cls.TOOL_DESCRIPTIONS.get(tool_name, f'🔧 {tool_name}')
            section += f"\n**{tool_desc}**\n"

            # Show relevant arguments based on tool type
            args_section = cls._format_tool_arguments(tool_name, tool_args)
            if args_section:
                section += args_section

        section += "\n"
        return section

    @classmethod
    def _format_tool_arguments(cls, tool_name: str, tool_args: Dict) -> str:
        """
        Format tool arguments based on tool type.

        Args:
            tool_name: Name of the tool
            tool_args: Tool arguments dictionary

        Returns:
            Formatted arguments section
        """
        args_lines = []

        if tool_name == 'search_code' and 'query' in tool_args:
            args_lines.append(f"  - Query: `{tool_args['query']}`")

        elif tool_name == 'read_file' and 'path' in tool_args:
            args_lines.append(f"  - File: `{tool_args['path']}`")
            if 'offset' in tool_args or 'limit' in tool_args:
                offset = tool_args.get('offset', 0)
                limit = tool_args.get('limit', 'all')
                args_lines.append(f"  - Lines: {offset} to {limit}")

        elif tool_name == 'ls' and 'path' in tool_args:
            args_lines.append(f"  - Directory: `{tool_args['path']}`")

        elif tool_name == 'grep' and 'pattern' in tool_args:
            args_lines.append(f"  - Pattern: `{tool_args['pattern']}`")
            if 'path' in tool_args:
                args_lines.append(f"  - In: `{tool_args['path']}`")

        elif tool_name == 'glob' and 'pattern' in tool_args:
            args_lines.append(f"  - Pattern: `{tool_args['pattern']}`")

        elif tool_name == 'write_file' and 'path' in tool_args:
            args_lines.append(f"  - File: `{tool_args['path']}`")
            content_len = len(tool_args.get('content', ''))
            args_lines.append(f"  - Size: {content_len} characters")

        elif tool_name == 'edit_file' and 'path' in tool_args:
            args_lines.append(f"  - File: `{tool_args['path']}`")

        else:
            # Show first few args for unknown tools
            shown_args = 0
            for key, value in tool_args.items():
                if shown_args >= 3:  # Limit to 3 args
                    break
                value_str = str(value)
                if len(value_str) > 50:
                    value_str = value_str[:50] + "..."
                args_lines.append(f"  - {key}: `{value_str}`")
                shown_args += 1

        return "\n".join(args_lines) + "\n" if args_lines else ""

    @classmethod
    def _format_tool_result(cls, tool_name: str, content: Any) -> str:
        """
        Format tool result section.

        Args:
            tool_name: Name of the tool that produced the result
            content: Result content

        Returns:
            Formatted result section, or empty string if content is empty
        """
        result_content = str(content).strip()

        # Skip empty results, empty lists, or just "[]"
        if not result_content or result_content == "[]" or len(result_content) == 0:
            return ""

        section = f"**✅ Tool result from {tool_name}:**\n"

        # Count lines and characters
        line_count = result_content.count('\n') + 1
        char_count = len(result_content)

        # Show metadata about the result, not the actual content
        if line_count > 1:
            section += f"  - Retrieved {line_count} lines ({char_count} characters)\n"
        else:
            section += f"  - Retrieved {char_count} characters\n"

        section += "\n"
        return section

    @classmethod
    def format_completion_summary(
        cls,
        step_count: int,
        estimated_tokens: int,
        agent_messages: List[Any]
    ) -> str:
        """
        Format a completion summary showing steps, tokens, and tool usage.

        Args:
            step_count: Number of steps executed
            estimated_tokens: Estimated token usage
            agent_messages: List of messages from agent execution

        Returns:
            Formatted completion summary
        """
        summary = "✅ **Deep Agent Analysis Complete**\n\n"

        # Extract tool call information from messages
        tool_calls_summary = cls._extract_tool_calls_summary(agent_messages)

        if tool_calls_summary:
            summary += "**📊 Execution Summary:**\n"
            summary += f"- Steps executed: {step_count}\n"
            summary += f"- Estimated tokens: {estimated_tokens:,}\n"
            summary += f"- Tools used: {tool_calls_summary['total_calls']}\n\n"

            if tool_calls_summary['by_tool']:
                summary += "**🔧 Tools Used:**\n"
                for tool_name, count in sorted(
                    tool_calls_summary['by_tool'].items(),
                    key=lambda x: x[1],
                    reverse=True
                ):
                    tool_desc = cls.TOOL_DESCRIPTIONS.get(tool_name, tool_name)
                    # Remove emoji from description for cleaner summary
                    tool_desc_clean = tool_desc.split(' ', 1)[1] if ' ' in tool_desc else tool_desc
                    summary += f"  - {tool_desc_clean}: {count}x\n"
        else:
            summary += "**📊 Execution Summary:**\n"
            summary += f"- Steps executed: {step_count}\n"
            summary += f"- Estimated tokens: {estimated_tokens:,}\n"

        return summary

    @classmethod
    def _extract_tool_calls_summary(cls, agent_messages: List[Any]) -> Dict[str, Any]:
        """
        Extract summary of tool calls from agent messages.

        Args:
            agent_messages: List of messages from agent execution

        Returns:
            Dictionary with tool call statistics
        """
        tool_calls_by_name = {}
        total_calls = 0

        for msg in agent_messages:
            # Check if message has tool_calls attribute
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tool_name = tool_call.get('name', 'unknown')
                    tool_calls_by_name[tool_name] = tool_calls_by_name.get(tool_name, 0) + 1
                    total_calls += 1

        if total_calls == 0:
            return {}

        return {
            'total_calls': total_calls,
            'by_tool': tool_calls_by_name
        }
