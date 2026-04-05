"""
Natural language routing chain.

Implements intent-based routing for non-slash-command messages
  0. AgentRouter — check for @agent mentions, capability matching
  1. IntentDetector — classify intent, then route based on intent:
       - deep_analysis → DeepAgent (complex multi-step reasoning)
       - ask_code → AskCodeWorkflow (simple code questions)
       - Other intents → QA_Handler (fallback)
  2. DeepAgent (LangGraph) — only when intent is deep_analysis (complex multi-step reasoning with tools)
  3. QA_Handler (final fallback for general queries)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from graph_kb_api.core.intent_detector import IntentDetector
from graph_kb_api.schemas.intent import IntentResult

if TYPE_CHECKING:
    from graph_kb_api.core.llm import LLMService

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """Result returned by the natural language routing chain."""

    success: bool
    source: str  # "agent_router", "deep_agent", "intent_detector", or "qa_handler"
    response: str = ""
    context_items: List[Dict[str, Any]] = field(default_factory=list)
    mermaid_code: Optional[str] = None
    intent_result: Optional[IntentResult] = None
    intent: Optional[str] = None  # The detected intent name
    agent_type: Optional[str] = None  # Selected agent type if routed via AgentRouter
    agent_capability: Optional[Any] = None  # AgentCapability if available


class NaturalLanguageHandler:
    """Intent-based routing: AgentRouter → IntentDetector → route by intent.

    When a non-slash-command message is received:
    1. Check for explicit @agent mentions via AgentRouter
    2. Classify intent via IntentDetector
    3. Route based on detected intent:
       - deep_analysis → DeepAgent (complex analysis)
       - ask_code → AskCodeWorkflow (simple questions)
       - Other → QA_Handler (fallback)
    """

    def __init__(self, llm_service: "LLMService", facade: Any = None) -> None:
        self.llm_service = llm_service
        self.facade = facade
        self.intent_detector = IntentDetector(llm=llm_service)
        self._agent_router = None  # Lazy-loaded

        self.facade = facade

    @property
    def agent_router(self):
        """Lazily initialize the AgentRouter."""
        if self._agent_router is None:
            from graph_kb_api.core.agent_router import AgentRouter

            self._agent_router = AgentRouter(
                llm_service=self.llm_service,
                intent_detector=self.intent_detector,
            )
        return self._agent_router

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def route(
        self,
        query: str,
        repo_id: str = "",
        *,
        progress_callback: Any = None,
    ) -> RouteResult:
        """Route *query* through the intent-based routing chain.

        Args:
            query: The user's natural language message.
            repo_id: Repository identifier (may be empty).
            progress_callback: Optional async callable for progress events.

        Returns:
            A ``RouteResult`` describing which tier handled the query and
            the generated response.
        """

        # Step 0 — Agent Router (check for @agent mentions)
        agent_result = await self._try_agent_router(query, progress_callback)
        if agent_result is not None and agent_result.success:
            # If agent was explicitly mentioned, route to that agent
            if agent_result.agent_type:
                return await self._route_to_agent(
                    agent_result.agent_type,
                    agent_result.cleaned_query or query,
                    repo_id,
                    progress_callback,
                    agent_result.agent_capability,
                )

        # Step 1 — Classify intent first
        intent_result = await self._classify_intent(query, progress_callback)

        if intent_result is None:
            # Fall through to QA handler if intent classification fails
            return await self._qa_handler(query, repo_id, progress_callback)

        # Store the intent for response
        intent = intent_result.intent_result.intent if intent_result.intent_result else None

        # Route based on detected intent
        if intent == "deep_analysis":
            logger.info("Routing to DeepAgent for complex analysis")
            return await self._try_deep_agent(query, repo_id, progress_callback)

        elif intent == "ask_code":
            logger.info("Routing to AskCodeWorkflow for simple question")
            return await self._try_ask_code(query, repo_id, progress_callback)

        else:
            # For other intents, return the intent result and let caller handle
            return intent_result

    # ------------------------------------------------------------------
    # Tier 0 – Agent Router
    # ------------------------------------------------------------------

    async def _try_agent_router(
        self,
        query: str,
        progress_callback: Any,
    ) -> Optional[RouteResult]:
        """Check for explicit agent mentions via AgentRouter.

        Returns a successful RouteResult when @agent is mentioned.
        """
        try:
            if progress_callback:
                await progress_callback(
                    "checking_agent", message="Checking for agent selection..."
                )

            agent_route = await self.agent_router.route(query)

            if agent_route.route_type == "agent_mention":
                return RouteResult(
                    success=True,
                    source="agent_router",
                    response="",
                    agent_type=agent_route.agent_type,
                    agent_capability=agent_route.agent_capability,
                )

            return None

        except Exception as exc:
            logger.warning("Agent routing failed (%s) — falling through", exc)
            return None

    async def _route_to_agent(
        self,
        agent_type: str,
        query: str,
        repo_id: str,
        progress_callback: Any,
        capability: Any = None,
    ) -> RouteResult:
        """Route query to a specific agent."""
        try:
            if progress_callback:
                await progress_callback(
                    "agent_routing",
                    message=f"Routing to {agent_type}...",
                )

            # Try to get the agent from registry
            try:
                from graph_kb_api.flows.v3.agents.registry import AgentRegistry

                agent = AgentRegistry.get_agent(agent_type)
                if agent is None:
                    return RouteResult(
                        success=False,
                        source="agent_router",
                        response=f"Agent '{agent_type}' not found. Use /agents to list available agents.",
                    )

                # Execute the agent
                task = {"description": query}
                state = {"repo_id": repo_id, "agent_context": {}}
                app_context = type("AppContext", (), {"llm": self.llm_service})()

                result = await agent.execute(task, state, app_context)

                return RouteResult(
                    success=True,
                    source="agent_router",
                    response=result.get("output", ""),
                    agent_type=agent_type,
                    agent_capability=capability,
                )

            except ImportError:
                # AgentRegistry not available, fall back to deep agent
                logger.info("AgentRegistry unavailable, using deep agent")
                return await self._try_deep_agent(query, repo_id, progress_callback) or RouteResult(
                    success=False,
                    source="agent_router",
                    response="Agent system unavailable. Please try again.",
                )

        except Exception as exc:
            logger.error("Agent execution failed: %s", exc)
            return RouteResult(
                success=False,
                source="agent_router",
                response=f"Agent execution failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Tier 1 – Intent Classification
    # ------------------------------------------------------------------

    async def _classify_intent(
        self,
        query: str,
        progress_callback: Any,
    ) -> Optional[RouteResult]:
        """Classify the query via the IntentDetector.

        Returns a successful ``RouteResult`` only when confidence >= 0.7.
        """
        try:
            if progress_callback:
                await progress_callback(
                    "detecting_intent", message="Detecting intent..."
                )

            intent_result = await self.intent_detector.detect(query)

            if intent_result.confidence < IntentDetector.CONFIDENCE_THRESHOLD:
                logger.info(
                    "Intent confidence %.2f < threshold — falling through to QA",
                    intent_result.confidence,
                )
                return None

            self.intent_detector.get_config(intent_result.intent)

            # Return the intent result for routing decision
            return RouteResult(
                success=True,
                source="intent_detector",
                response="",  # Empty - routing happens based on intent
                intent_result=intent_result,
                intent=intent_result.intent,
            )

        except Exception as exc:
            logger.warning("Intent detection failed (%s) — falling through", exc)
            return None

    # ------------------------------------------------------------------
    # Tier 2 – Deep Agent (only when intent is deep_analysis)
    # ------------------------------------------------------------------

    async def _try_deep_agent(
        self,
        query: str,
        repo_id: str,
        progress_callback: Any,
    ) -> Optional[RouteResult]:
        """Attempt to answer via the Deep Agent (LangGraph).

        Only used when intent classification indicates deep_analysis.
        (complex multi-step reasoning with tools).

        Returns ``None`` when the engine is unavailable or the workflow
        fails so the caller falls through to the next tier.
        """
        try:
            if progress_callback:
                await progress_callback("reasoning", message="Deep agent reasoning...")

            from graph_kb_api.flows.v3.graphs.deep_agent import (
                DeepAgentWorkflowEngine,
            )

            if self.facade is None:
                logger.debug("Facade unavailable — skipping Deep Agent")
                return None

            engine = DeepAgentWorkflowEngine(
                llm=self.llm_service,
                app_context=self.facade.app_context,
                checkpointer=None,
            )

            result = await engine.run(query=query, repo_id=repo_id)

            response_text = result.get("final_output", result.get("llm_response", ""))

            if not response_text:
                logger.info("Deep Agent returned empty response — falling through")
                return None

            return RouteResult(
                success=True,
                source="deep_agent",
                response=response_text,
                context_items=result.get("context_items", []),
                mermaid_code=result.get("mermaid_code"),
            )

        except ImportError:
            logger.warning("Deep Agent engine not available — skipping tier 1")
            return None
        except Exception as exc:
            logger.warning("Deep Agent failed (%s) — falling through", exc)
            return None

    # ------------------------------------------------------------------
    # Tier 2b – Ask Code Workflow (for simple questions)
    # ------------------------------------------------------------------

    async def _try_ask_code(
        self,
        query: str,
        repo_id: str,
        progress_callback: Any,
    ) -> Optional[RouteResult]:
        """Attempt to answer via the Ask Code workflow (lighter weight).

        Used for simple code questions that don't require deep analysis.

        Returns ``None`` when the engine is unavailable or the workflow
        fails so the caller falls through to the next tier.
        """
        try:
            if progress_callback:
                await progress_callback("reasoning", message="Analyzing code question...")

            from graph_kb_api.flows.v3.graphs.ask_code import (
                AskCodeWorkflowEngine,
            )

            if self.facade is None:
                logger.debug("Facade unavailable — skipping Ask Code workflow")
                return None

            engine = AskCodeWorkflowEngine(
                facade=self.facade,
                progress_callback=progress_callback,
            )

            result = await engine.run(query=query, repo_id=repo_id)

            response_text = result.get("final_output", result.get("llm_response", ""))

            if not response_text:
                logger.info("Ask Code workflow returned empty response — falling through")
                return None

            return RouteResult(
                success=True,
                source="ask_code",
                response=response_text,
                context_items=result.get("context_items", []),
                mermaid_code=result.get("mermaid_code"),
            )

        except ImportError:
            logger.warning("Ask Code engine not available — skipping")
            return None
        except Exception as exc:
            logger.warning("Ask Code workflow failed (%s) — falling through", exc)
            return None

    # ------------------------------------------------------------------
    # Tier 3 – QA Handler (final fallback)
    # ------------------------------------------------------------------

    async def _qa_handler(
        self,
        query: str,
        repo_id: str,
        progress_callback: Any,
    ) -> RouteResult:
        """Retrieval + LLM fallback — always returns a result."""
        try:
            if progress_callback:
                await progress_callback(
                    "qa_fallback", message="Searching code and generating answer..."
                )

            context_items: List[Dict[str, Any]] = []

            # Retrieve relevant code context when a facade is available
            if self.facade and repo_id:
                try:
                    retrieval_result = self.facade.retrieval_service.retrieve(
                        repo_id=repo_id,
                        query=query,
                        top_k=30,
                    )
                    if hasattr(retrieval_result, "context_items"):
                        for item in retrieval_result.context_items[:10]:
                            context_items.append(
                                {
                                    "file_path": item.file_path,
                                    "content": item.content[:500],
                                    "score": getattr(item, "score", 0),
                                }
                            )
                except Exception as exc:
                    logger.warning("Retrieval failed: %s", exc)

            # Build LLM prompt with retrieved context
            context_text = ""
            if context_items:
                snippets = "\n\n".join(
                    f"### {ci['file_path']}\n```\n{ci['content']}\n```"
                    for ci in context_items
                )
                context_text = f"Here is relevant code context:\n\n{snippets}\n\n"

            system_prompt = (
                "You are a helpful code assistant. Answer the user's question "
                "based on the provided code context. If no context is available, "
                "answer to the best of your ability and note the limitation."
            )
            user_prompt = f"{context_text}User question: {query}"

            response = await self.llm_service.a_generate_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            return RouteResult(
                success=True,
                source="qa_handler",
                response=response,
                context_items=context_items,
            )

        except Exception as exc:
            logger.error("QA handler failed: %s", exc)
            return RouteResult(
                success=False,
                source="qa_handler",
                response=(
                    "I'm sorry, I was unable to process your question. "
                    "Please try rephrasing or use /help for available commands."
                ),
            )


# ------------------------------------------------------------------
# Module-level singleton accessor
# ------------------------------------------------------------------

_handler: Optional[NaturalLanguageHandler] = None


def get_natural_language_handler(
    llm_service: Optional["LLMService"] = None,
    facade: Any = None,
) -> NaturalLanguageHandler:
    """Return (and lazily create) the global ``NaturalLanguageHandler``.

    On first call the *llm_service* argument is required.  Subsequent calls
    return the cached instance.
    """
    global _handler
    if _handler is None:
        if llm_service is None:
            from graph_kb_api.core.llm import LLMService as _LLMService

            llm_service = _LLMService()
        _handler = NaturalLanguageHandler(llm_service=llm_service, facade=facade)
    return _handler
