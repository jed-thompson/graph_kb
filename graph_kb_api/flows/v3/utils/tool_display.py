"""
Utility functions for formatting tool calls for user display.

This module provides centralized formatting logic for displaying tool calls
in plain English with appropriate emojis and context.
"""

from typing import Dict, List


class ToolDisplayFormatter:
    """Formats tool calls for user-friendly display."""

    # Tool emoji mapping
    TOOL_EMOJIS = {
        'search_code': '🔍',
        'get_symbol_info': '📋',
        'trace_call_chain': '🔗',
        'get_file_content': '📄',
        'get_related_files': '🔗',
        'execute_cypher_query': '🗄️'
    }

    # Tool description mapping
    TOOL_DESCRIPTIONS = {
        'search_code': 'Searching for code patterns',
        'get_symbol_info': 'Getting detailed symbol information',
        'trace_call_chain': 'Tracing function call chains',
        'get_file_content': 'Reading file contents',
        'get_related_files': 'Finding related files',
        'execute_cypher_query': 'Executing graph query'
    }

    @classmethod
    def get_tool_emoji(cls, tool_name: str) -> str:
        """
        Get emoji for tool name.

        Args:
            tool_name: Name of the tool

        Returns:
            Emoji string for the tool, or default 🔧 if not found
        """
        return cls.TOOL_EMOJIS.get(tool_name, '🔧')

    @classmethod
    def get_tool_description(cls, tool_name: str, args: Dict) -> str:
        """
        Get plain English description for tool call with context from arguments.

        Args:
            tool_name: Name of the tool
            args: Tool arguments dictionary

        Returns:
            Formatted description string with context
        """
        base_desc = cls.TOOL_DESCRIPTIONS.get(tool_name, tool_name)

        # Add context from arguments based on tool type
        if tool_name == 'search_code' and 'query' in args:
            query = str(args['query'])[:50]
            return f"{base_desc}: \"{query}...\""

        elif tool_name == 'get_symbol_info' and 'symbol_name' in args:
            symbol = args['symbol_name']
            return f"{base_desc}: `{symbol}`"

        elif tool_name == 'trace_call_chain' and 'function_name' in args:
            func = args['function_name']
            return f"{base_desc} from `{func}`"

        elif tool_name == 'get_file_content' and 'file_path' in args:
            file_path = args['file_path'].split('/')[-1]  # Just filename
            return f"{base_desc}: `{file_path}`"

        elif tool_name == 'get_related_files' and 'file_path' in args:
            file_path = args['file_path'].split('/')[-1]
            return f"{base_desc} for `{file_path}`"

        else:
            return base_desc

    @classmethod
    def format_tool_call(cls, tool_name: str, args: Dict, index: int = None) -> str:
        """
        Format a single tool call for display.

        Args:
            tool_name: Name of the tool
            args: Tool arguments dictionary
            index: Optional index number for the tool call

        Returns:
            Formatted string like "1. 🔍 Searching for code patterns: "query...""
        """
        emoji = cls.get_tool_emoji(tool_name)
        desc = cls.get_tool_description(tool_name, args)

        if index is not None:
            return f"{index}. {emoji} {desc}"
        else:
            return f"{emoji} {desc}"

    @classmethod
    def format_tool_calls_list(cls, tool_calls: List[Dict]) -> str:
        """
        Format a list of tool calls for display.

        Args:
            tool_calls: List of tool call dictionaries with 'name' and 'args' keys

        Returns:
            Formatted string with numbered list of tool calls
        """
        descriptions = []
        for i, tc in enumerate(tool_calls, 1):
            tool_name = tc.get('name', 'unknown')
            args = tc.get('args', {})
            descriptions.append(cls.format_tool_call(tool_name, args, index=i))

        return '\n'.join(descriptions)

    @classmethod
    def format_tool_history(cls, tool_calls_history: List[Dict]) -> str:
        """
        Format tool call history with status indicators.

        Args:
            tool_calls_history: List of tool call history items with 'tool_name', 'args', and 'status'

        Returns:
            Formatted string with completed and pending tool calls
        """
        completed_calls = cls.get_completed_calls(tool_calls_history)
        pending_calls = cls.get_pending_calls(tool_calls_history)

        sections = []

        if completed_calls:
            sections.append("**✅ Completed:**\n")
            for i, tc in enumerate(completed_calls, 1):
                tool_name = tc.get('tool_name', 'unknown')
                args = tc.get('args', {})
                sections.append(cls.format_tool_call(tool_name, args, index=i))

        if pending_calls:
            if sections:
                sections.append("")  # Add blank line between sections
            sections.append("**⏳ In Progress:**\n")
            start_index = len(completed_calls) + 1
            for i, tc in enumerate(pending_calls, start_index):
                tool_name = tc.get('tool_name', 'unknown')
                args = tc.get('args', {})
                sections.append(cls.format_tool_call(tool_name, args, index=i))

        return '\n'.join(sections)

    @classmethod
    def format_tool_summary(cls, tool_calls_history: List[Dict]) -> str:
        """
        Format a summary of tool calls (e.g., "3 total (2 completed, 1 in progress)").

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            Summary string
        """
        completed = cls.count_completed_calls(tool_calls_history)
        pending = cls.count_pending_calls(tool_calls_history)
        total = completed + pending

        if pending > 0:
            return f"{total} total ({completed} completed, {pending} in progress)"
        else:
            return f"{total} completed"

    @classmethod
    def count_completed_calls(cls, tool_calls_history: List[Dict]) -> int:
        """
        Count completed tool calls in history.

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            Number of completed tool calls
        """
        return len([tc for tc in tool_calls_history if tc.get('status') == 'completed'])

    @classmethod
    def count_pending_calls(cls, tool_calls_history: List[Dict]) -> int:
        """
        Count pending tool calls in history.

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            Number of pending tool calls
        """
        return len([tc for tc in tool_calls_history if tc.get('status') == 'pending'])

    @classmethod
    def get_completed_calls(cls, tool_calls_history: List[Dict]) -> List[Dict]:
        """
        Get all completed tool calls from history.

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            List of completed tool call records
        """
        return [tc for tc in tool_calls_history if tc.get('status') == 'completed']

    @classmethod
    def get_pending_calls(cls, tool_calls_history: List[Dict]) -> List[Dict]:
        """
        Get all pending tool calls from history.

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            List of pending tool call records
        """
        return [tc for tc in tool_calls_history if tc.get('status') == 'pending']

    @classmethod
    def build_completed_tools_section(cls, tool_calls_history: List[Dict]) -> str:
        """
        Build a formatted section showing completed tool calls for final display.

        This is typically used at the end of a workflow to show what tools were used.

        Args:
            tool_calls_history: List of tool call history items

        Returns:
            Formatted section with completed tools, or empty string if no completed calls
        """
        completed_calls = cls.get_completed_calls(tool_calls_history)

        if not completed_calls:
            return ""

        tool_summary = "\n\n---\n\n**🔧 Tools Used:**\n\n"
        for i, tc in enumerate(completed_calls, 1):
            tool_name = tc.get('tool_name', 'unknown')
            args = tc.get('args', {})
            tool_summary += cls.format_tool_call(tool_name, args, index=i) + "\n"

        return tool_summary

    @classmethod
    def create_tool_call_records(cls, tool_calls: List[Dict], iteration: int) -> List[Dict]:
        """
        Create tool call history records from LLM response tool calls.

        Args:
            tool_calls: List of tool calls from LLM response (with 'name' and 'args')
            iteration: Current iteration number

        Returns:
            List of tool call history records with 'iteration', 'tool_name', 'args', 'status'
        """
        records = []
        for tc in tool_calls:
            records.append({
                'iteration': iteration,
                'tool_name': tc.get('name', 'unknown'),
                'args': tc.get('args', {}),
                'status': 'pending'
            })
        return records

    @classmethod
    def build_cumulative_tool_display(
        cls,
        existing_history: List[Dict],
        new_tool_calls: List[Dict]
    ) -> List[str]:
        """
        Build cumulative tool call display showing completed and new pending calls.

        Args:
            existing_history: Existing tool call history from state
            new_tool_calls: New tool calls from current LLM response

        Returns:
            List of formatted strings for display
        """
        all_descriptions = []

        # Add completed tool calls from history
        completed_calls = cls.get_completed_calls(existing_history)
        if completed_calls:
            all_descriptions.append("**✅ Completed:**\n")
            for i, tc in enumerate(completed_calls, 1):
                tool_name = tc.get('tool_name', 'unknown')
                args = tc.get('args', {})
                all_descriptions.append(cls.format_tool_call(tool_name, args, index=i))
            all_descriptions.append("")  # Blank line

        # Add current pending tool calls
        if new_tool_calls:
            all_descriptions.append("**⏳ In Progress:**\n")
            all_descriptions.append(cls.format_tool_calls_list(new_tool_calls))

        return all_descriptions

    @classmethod
    def build_completed_tools_display(cls, completed_calls: List[Dict]) -> str:
        """
        Build display string for completed tool calls.

        Args:
            completed_calls: List of completed tool call records

        Returns:
            Formatted string with completed tools
        """
        if not completed_calls:
            return ""

        tool_display = "**✅ Completed:**\n\n"
        for i, tc in enumerate(completed_calls, 1):
            tool_name = tc.get('tool_name', 'unknown')
            args = tc.get('args', {})
            tool_display += cls.format_tool_call(tool_name, args, index=i) + "\n"

        return tool_display

    @classmethod
    def update_tool_history_status(
        cls,
        existing_history: List[Dict],
        completed_calls: List[Dict]
    ) -> List[Dict]:
        """
        Update tool call history by marking matching pending calls as completed.

        Args:
            existing_history: Existing tool call history from state
            completed_calls: Newly completed tool calls

        Returns:
            Updated history with completed status applied
        """
        updated_history = []

        for existing_call in existing_history:
            if existing_call.get('status') == 'pending':
                # Check if this call was just completed
                matching_completed = next(
                    (tc for tc in completed_calls
                     if tc['tool_name'] == existing_call['tool_name']
                     and tc['iteration'] == existing_call['iteration']),
                    None
                )
                if matching_completed:
                    updated_history.append(matching_completed)
                else:
                    updated_history.append(existing_call)
            else:
                updated_history.append(existing_call)

        return updated_history
