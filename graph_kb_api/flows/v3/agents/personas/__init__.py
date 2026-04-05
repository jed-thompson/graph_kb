"""Agent persona prompt templates.

Loads agent system prompts from markdown files in the personas/ directory tree.
Use ``get_agent_prompt_manager()`` to access the singleton manager.
"""

from .prompt_manager import AgentPromptManager, get_agent_prompt_manager

__all__ = [
    "AgentPromptManager",
    "get_agent_prompt_manager",
]
