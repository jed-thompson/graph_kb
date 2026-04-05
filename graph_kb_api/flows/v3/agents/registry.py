"""
Agent registry for multi-agent workflow system.

Provides a centralized registry for discovering and instantiating
specialized agents without hard-coding agent types.
"""

from typing import TYPE_CHECKING, Dict, List, Optional

from .base_agent import AgentCapability, BaseAgent

if TYPE_CHECKING:
    from graph_kb_api.utils.enhanced_logger import EnhancedLogger

    logger = EnhancedLogger(__name__)


class AgentRegistry:
    """
    Registry for discovering and instantiating agents.

    This class implements the Registry Pattern, allowing:
    - Dynamic registration of new agent types
    - Type-safe agent retrieval
    - Capability listing for introspection
    """

    _agents: Dict[str, type[BaseAgent]] = {}

    @classmethod
    def register(cls, agent_class: type[BaseAgent]) -> None:
        """
        Register an agent class.

        Args:
            agent_class: Agent class to register (class, not instance)
        """
        try:
            # Instantiate to access the @property-based capability
            instance = agent_class()
            capability = instance.capability
            cls._agents[capability.agent_type] = agent_class

            if TYPE_CHECKING:
                logger.info(
                    f"Registered agent: {capability.agent_type}",
                    data={
                        "agent_type": capability.agent_type,
                        "supported_tasks": len(capability.supported_tasks),
                        "description": capability.description,
                    },
                )
        except Exception as e:
            if TYPE_CHECKING:
                logger.error(
                    f"Failed to register agent: {agent_class.__name__}: {e}",
                    exc_info=True,
                )
            raise

    @classmethod
    def get_agent(cls, agent_type: str) -> Optional[BaseAgent]:
        """
        Get an agent instance by type.

        Args:
            agent_type: The type identifier (e.g., "code_analyst")

        Returns:
            Agent instance if registered, None otherwise
        """
        agent_class = cls._agents.get(agent_type)
        if agent_class:
            return agent_class()
        return None

    @classmethod
    def list_capabilities(cls) -> List[AgentCapability]:
        """
        List all available agent capabilities.

        Returns:
            List of AgentCapability for all registered agents
        """
        return [agent_class().capability for agent_class in cls._agents.values()]

    @classmethod
    def list_agent_types(cls) -> List[str]:
        """
        List all registered agent type identifiers.

        Returns:
            List of agent type strings
        """
        return list(cls._agents.keys())

    @classmethod
    def clear(cls) -> None:
        """
        Clear all registered agents.

        Useful for testing or re-initialization.
        """
        cls._agents.clear()
        if TYPE_CHECKING:
            logger.info("Agent registry cleared")
