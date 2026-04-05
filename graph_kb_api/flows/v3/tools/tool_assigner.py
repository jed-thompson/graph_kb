"""
Tool assigner for multi-agent workflow system.

Dynamically assigns tools to agents based on task context
and agent capabilities.
"""

from typing import Any, Dict, List, Optional

from graph_kb_api.flows.v3.models.types import AgentTask
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ToolAssigner:
    """
    Dynamically assigns tools to agents based on task context and agent capabilities.

    Uses task and agent type to determine which tools are appropriate.
    """

    # Tool categories for grouping tools by functionality
    TOOL_CATEGORIES = {
        "analysis": [
            "search_code",
            "get_symbol_info",
            "trace_call_chain",
        ],
        "file_access": [
            "get_file_content",
            "get_related_files",
        ],
        "repository": [
            "list_files",
            "search_code",
        ],
        "graph": [
            "execute_cypher_query",
        ],
    }

    # Agent-specific tool requirements
    # Maps agent_type to required tool categories
    AGENT_TOOL_REQUIREMENTS = {
        "code_analyst": ["analysis", "file_access"],
        "code_generator": ["file_access"],
        "researcher": ["analysis", "repository"],
        "architect": ["analysis", "repository"],
        "security": ["analysis", "repository", "file_access"],
    }

    def __init__(self, all_tools: List[Any]):
        """
        Initialize tool assigner.

        Args:
            all_tools: List of all available tools (tool instances or callables)
        """
        self.all_tools = all_tools
        self._build_tool_index()

    def _build_tool_index(self) -> None:
        """
        Build index of tools by category for faster lookup.

        Maps tool names to their categories.
        """
        self.tool_index: Dict[str, List[str]] = {
            "analysis": [],
            "file_access": [],
            "repository": [],
            "graph": [],
        }

        for tool in self.all_tools:
            tool_name = getattr(tool, "name", getattr(tool, "__name__", "unknown"))

            for category, tool_list in self.TOOL_CATEGORIES.items():
                if tool_name in tool_list:
                    self.tool_index[category].append(tool_name)
                    break

        logger.info(
            "Tool index built",
            data={
                "total_tools": len(self.all_tools),
                "categories": {k: len(v) for k, v in self.tool_index.items()},
            },
        )

    def assign_tools(self, task: AgentTask, agent_type: str) -> List[Any]:
        """
        Assign appropriate tools for a task and agent type.

        Args:
            task: Task dictionary containing description and context
            agent_type: The agent type to assign tools to

        Returns:
            List of tools (or tool objects/callables) for the agent
        """
        # Get required categories for this agent type
        required_categories = self.AGENT_TOOL_REQUIREMENTS.get(
            agent_type,
            ["analysis"],  # Default to analysis tools
        )

        # Collect tools from required categories
        assigned_tools = []
        seen_tools = set()

        for category in required_categories:
            tool_names = self.tool_index.get(category, [])
            for tool_name in tool_names:
                if tool_name not in seen_tools:
                    # Find tool in all_tools
                    tool = self._find_tool_by_name(tool_name)
                    if tool:
                        assigned_tools.append(tool)
                        seen_tools.add(tool_name)

        logger.info(
            f"Assigned {len(assigned_tools)} tools for agent {agent_type}",
            data={
                "agent_type": agent_type,
                "categories": required_categories,
                "tool_names": [
                    t.name if hasattr(t, "name") else str(t) for t in assigned_tools
                ],
            },
        )

        return assigned_tools

    def _find_tool_by_name(self, name: str) -> Optional[Any]:
        """
        Find a tool by its name.

        Args:
            name: Tool name to find

        Returns:
            Tool instance if found, None otherwise
        """
        for tool in self.all_tools:
            tool_name = getattr(tool, "name", getattr(tool, "__name__", "unknown"))
            if tool_name == name:
                return tool
        return None

    def get_tool_categories(self) -> Dict[str, List[str]]:
        """
        Get all tool categories.

        Returns:
            Dictionary mapping categories to tool names
        """
        return self.TOOL_CATEGORIES

    def get_agent_tool_requirements(self) -> Dict[str, List[str]]:
        """
        Get tool requirements for each agent type.

        Returns:
            Dictionary mapping agent types to required tool categories
        """
        return self.AGENT_TOOL_REQUIREMENTS
