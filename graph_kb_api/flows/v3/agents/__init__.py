"""
Agent package for multi-agent workflow system.

This package provides:
- Base agent class and capability definition
- Agent registry for discovering and instantiating specialized agents
- Initial agent implementations (CodeAnalyst, CodeGenerator, Researcher)
"""

from .base_agent import AgentResult, AgentTask, BaseAgent
from .registry import AgentRegistry

__all__ = [
    'AgentResult',
    'AgentTask',
    'BaseAgent',
    'AgentRegistry',
]
