"""
Agent routing service for hybrid command/agent selection.

Implements Option A: Hybrid approach where:
- Commands (`/ingest`, `/diff`) remain for operations
- Agent mentions (`@analyst`, `@architect`) select specific agents
- Natural language falls back through IntentDetector → AgentRegistry

The router bridges IntentDetector (operations) and AgentRegistry (agents).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from graph_kb_api.core.intent_detector import IntentDetector
    from graph_kb_api.core.llm import LLMService
    from graph_kb_api.flows.v3.agents.base_agent import AgentCapability

logger = logging.getLogger(__name__)


@dataclass
class AgentRouteResult:
    """Result from agent routing decision."""

    route_type: str  # "agent_mention", "command", "intent", "fallback"
    agent_type: Optional[str] = None
    command: Optional[str] = None
    intent: Optional[str] = None
    confidence: float = 0.0
    cleaned_query: str = ""  # Query with @agent removed
    agent_capability: Optional[AgentCapability] = None
    params: Dict[str, Any] = field(default_factory=dict)


class AgentRouter:
    """
    Routes messages to agents or commands using hybrid approach.

    Priority:
    1. Explicit agent mention (@agent_name)
    2. Explicit command (/command)
    3. IntentDetector classification
    4. Agent capability matching (future: semantic routing)
    5. Fallback to default agent
    """

    # Regex to match @agent mentions at start or embedded in message
    AGENT_MENTION_PATTERN = re.compile(r"@([a-z_][a-z0-9_]*)", re.IGNORECASE)

    # Agent aliases for user-friendly names
    AGENT_ALIASES = {
        "analyst": "code_analyst",
        "analyzer": "code_analyst",
        "architect": "architect_agent",
        "arch": "architect_agent",
        "generator": "code_generator",
        "gen": "code_generator",
        "researcher": "researcher",
        "research": "researcher",
        "reviewer": "reviewer_critic_agent",
        "critic": "reviewer_critic_agent",
        "planner": "tool_planner_agent",
        "tools": "tool_planner_agent",
        "consistency": "consistency_checker_agent",
        "checker": "consistency_checker_agent",
        "lead": "lead_engineer_agent",
        "engineer": "lead_engineer_agent",
        "doc": "doc_extractor_agent",
        "docs": "doc_extractor_agent",
        "extractor": "doc_extractor_agent",
    }

    def __init__(
        self,
        llm_service: "LLMService",
        intent_detector: Optional["IntentDetector"] = None,
    ) -> None:
        self.llm_service = llm_service
        self.intent_detector = intent_detector

    async def route(self, query: str) -> AgentRouteResult:
        """
        Route a query to determine agent/command/intent.

        Args:
            query: The user's message (may contain @agent or /command)

        Returns:
            AgentRouteResult with routing decision and cleaned query
        """
        # Step 1: Check for explicit agent mention
        agent_result = self._parse_agent_mention(query)
        if agent_result:
            return agent_result

        # Step 2: Check for explicit command
        command_result = self._parse_command(query)
        if command_result:
            return command_result

        # Step 3: Use IntentDetector for operation classification
        if self.intent_detector:
            intent_result = await self._route_via_intent(query)
            if intent_result and intent_result.confidence >= 0.7:
                return intent_result

        # Step 4: Try agent capability matching
        capability_result = await self._match_agent_capability(query)
        if capability_result:
            return capability_result

        # Step 5: Fallback to default
        return AgentRouteResult(
            route_type="fallback",
            agent_type="code_analyst",
            cleaned_query=query,
            confidence=0.0,
        )

    def _parse_agent_mention(self, query: str) -> Optional[AgentRouteResult]:
        """Parse @agent_name from query and resolve to agent type."""
        match = self.AGENT_MENTION_PATTERN.search(query)
        if not match:
            return None

        mentioned_name = match.group(1).lower()

        # Resolve alias to actual agent type
        agent_type = self.AGENT_ALIASES.get(mentioned_name, mentioned_name)

        # Verify agent exists in registry
        capability = self._get_agent_capability(agent_type)
        if capability is None:
            logger.warning(
                "Unknown agent mentioned: @%s (resolved to %s)",
                mentioned_name,
                agent_type,
            )
            # Still return the mention but without capability
            return AgentRouteResult(
                route_type="agent_mention",
                agent_type=agent_type,
                cleaned_query=self.AGENT_MENTION_PATTERN.sub("", query).strip(),
                confidence=1.0,  # Explicit mention = high confidence
            )

        logger.info("Agent mention resolved: @%s → %s", mentioned_name, agent_type)

        return AgentRouteResult(
            route_type="agent_mention",
            agent_type=agent_type,
            cleaned_query=self.AGENT_MENTION_PATTERN.sub("", query).strip(),
            confidence=1.0,
            agent_capability=capability,
        )

    def _parse_command(self, query: str) -> Optional[AgentRouteResult]:
        """Parse /command from query."""
        query_stripped = query.strip()
        if not query_stripped.startswith("/"):
            return None

        # Extract command and args
        parts = query_stripped.split(maxsplit=1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        return AgentRouteResult(
            route_type="command",
            command=command,
            cleaned_query=args,
            confidence=1.0,
            params={"raw_command": command, "args": args},
        )

    async def _route_via_intent(self, query: str) -> Optional[AgentRouteResult]:
        """Use IntentDetector to classify query into an operation."""
        try:
            intent_result = await self.intent_detector.detect(query)

            # Map intent to appropriate agent
            agent_type = self._intent_to_agent(intent_result.intent)
            self.intent_detector.get_config(intent_result.intent)

            return AgentRouteResult(
                route_type="intent",
                intent=intent_result.intent,
                agent_type=agent_type,
                confidence=intent_result.confidence,
                cleaned_query=query,
                params=intent_result.params,
            )

        except Exception as exc:
            logger.warning("Intent detection failed: %s", exc)
            return None

    async def _match_agent_capability(self, query: str) -> Optional[AgentRouteResult]:
        """
        Match query to agent based on supported tasks.

        Uses LLM to classify which agent's capabilities best match the query.
        """
        try:
            capabilities = self._list_agent_capabilities()
            if not capabilities:
                return None

            # Build capability descriptions for LLM
            cap_descriptions = "\n".join(
                f"- {cap.agent_type}: {cap.description}\n"
                f"  Tasks: {', '.join(cap.supported_tasks)}"
                for cap in capabilities
            )

            system_prompt = (
                "You are a routing classifier. Select the best agent for the user's query.\n\n"
                f"Available agents:\n{cap_descriptions}\n\n"
                "Respond with ONLY the agent_type that best matches, or 'none' if no match."
            )

            response = await self.llm_service.a_generate_response(
                system_prompt=system_prompt,
                user_prompt=f"Query: {query}",
            )

            agent_type = response.strip().lower()

            if agent_type == "none" or agent_type not in {c.agent_type for c in capabilities}:
                return None

            capability = self._get_agent_capability(agent_type)

            return AgentRouteResult(
                route_type="capability_match",
                agent_type=agent_type,
                cleaned_query=query,
                confidence=0.6,  # Lower confidence for capability matching
                agent_capability=capability,
            )

        except Exception as exc:
            logger.warning("Capability matching failed: %s", exc)
            return None

    def _intent_to_agent(self, intent: str) -> str:
        """Map intent names to appropriate agent types."""
        INTENT_AGENT_MAP = {
            "ask_code": "code_analyst",
            "generate_spec": "architect_agent",
            "generate_doc": "doc_extractor_agent",
            # Default for most operations
            "default": "code_analyst",
        }
        return INTENT_AGENT_MAP.get(intent, INTENT_AGENT_MAP["default"])

    def _get_agent_capability(self, agent_type: str) -> Optional[AgentCapability]:
        """Get capability from AgentRegistry."""
        try:
            from graph_kb_api.flows.v3.agents.registry import AgentRegistry

            agent = AgentRegistry.get_agent(agent_type)
            if agent:
                return agent.capability
        except ImportError:
            logger.debug("AgentRegistry not available")
        except Exception as exc:
            logger.debug("Failed to get agent capability: %s", exc)
        return None

    def _list_agent_capabilities(self) -> List[AgentCapability]:
        """List all available agent capabilities."""
        try:
            from graph_kb_api.flows.v3.agents.registry import AgentRegistry

            return AgentRegistry.list_capabilities()
        except ImportError:
            logger.debug("AgentRegistry not available")
            return []
        except Exception as exc:
            logger.warning("Failed to list capabilities: %s", exc)
            return []

    @classmethod
    def get_available_agents(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get all available agents with their aliases and descriptions.

        Returns dict mapping agent_type to {aliases, description, tasks}.
        """
        agents_info = {}

        # Get aliases mapping
        alias_to_type: Dict[str, List[str]] = {}
        for alias, agent_type in cls.AGENT_ALIASES.items():
            if agent_type not in alias_to_type:
                alias_to_type[agent_type] = []
            alias_to_type[agent_type].append(alias)

        # Get capabilities from registry
        try:
            from graph_kb_api.flows.v3.agents.registry import AgentRegistry

            for cap in AgentRegistry.list_capabilities():
                agents_info[cap.agent_type] = {
                    "aliases": alias_to_type.get(cap.agent_type, []),
                    "description": cap.description,
                    "tasks": cap.supported_tasks,
                }
        except ImportError:
            pass

        return agents_info


# Module-level accessor
_router: Optional[AgentRouter] = None


def get_agent_router(
    llm_service: Optional["LLMService"] = None,
    intent_detector: Optional["IntentDetector"] = None,
) -> AgentRouter:
    """Return (and lazily create) the global AgentRouter."""
    global _router
    if _router is None:
        if llm_service is None:
            from graph_kb_api.core.llm import LLMService as _LLMService

            llm_service = _LLMService()
        if intent_detector is None:
            from graph_kb_api.core.intent_detector import IntentDetector

            intent_detector = IntentDetector(llm=llm_service)
        _router = AgentRouter(llm_service=llm_service, intent_detector=intent_detector)
    return _router
