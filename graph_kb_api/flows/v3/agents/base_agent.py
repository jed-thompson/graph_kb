"""
Base agent class for multi-agent workflow system.

Defines the contract that all specialized agents must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from graph_kb_api.flows.v3.models import AgentCapability, AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState


class BaseAgent(ABC):
    """
    Base class for all specialized agents.

    All agents must implement:
    - capability property: Returns AgentCapability describing the agent
    - execute method: Executes the assigned task
    """

    @property
    @abstractmethod
    def capability(self) -> AgentCapability:
        """
        Return agent's capability description.

        Returns:
            AgentCapability with agent type, supported tasks, tools, and description
        """
        pass

    @abstractmethod
    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """
        Execute assigned task.

        Args:
            task: Task definition containing description and context
            state: Current workflow state (read-only access)
            workflow_context: Application context with LLM and services

        Returns:
            AgentResult containing output, tokens, and optional error
        """
        pass
