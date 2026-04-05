"""LangChain Agent integration for Graph KB tools.

This module provides an AgentExecutor-based agent that can use
Graph KB tools for code exploration and question answering.
"""

from .code_agent import CodeAgent, create_code_agent

__all__ = [
    "CodeAgent",
    "create_code_agent",
]
