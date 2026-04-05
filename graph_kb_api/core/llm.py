"""
LLM service with retry logic and graceful degradation.

Extends BaseChatModel to act as a drop-in replacement for LangGraph agents
while providing:
- Exponential-backoff retries for transient failures
- Provider abstraction (OpenAI / Ollama)
- Hot-swap model capability
- Graceful degradation with retrieval-only fallback
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, cast

from langchain.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableBinding
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import SecretStr

from graph_kb_api.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
MAX_RETRIES: int = 3
INITIAL_BACKOFF_SECONDS: float = 1.0
BACKOFF_MULTIPLIER: float = 2.0

RETRIEVAL_ONLY_DISCLAIMER = (
    "⚠️ The LLM service is currently unavailable. "
    "The following answer is based solely on code retrieval results "
    "and has not been processed by the language model."
)


class LLMService(BaseChatModel):
    """Chat model with retry logic, provider abstraction, and graceful degradation.

    Extends BaseChatModel so it can be used as a drop-in replacement
    in LangGraph workflows while preserving retry logic and hot-swap capability.
    """

    @property
    def _llm_type(self) -> str:
        return "llm_service"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "provider": self._provider,
            "model": self.model_name,
            "temperature": self._temperature,
        }

    def __init__(self) -> None:
        super().__init__()
        logger.info("[LLM] Initializing LLMService (provider=%s)", settings.llm_provider)

        if settings.llm_provider == "ollama":
            try:
                from langchain_community.chat_models import ChatOllama
            except ImportError:
                raise RuntimeError(
                    "langchain-community is not installed. "
                    "Add 'langchain-community' to requirements.api.txt and rebuild the Docker image."
                )

            logger.info(
                "[LLM] Using Ollama model=%s, base_url=%s",
                settings.ollama_model,
                settings.ollama_base_url,
            )
            self._llm = ChatOllama(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                temperature=settings.llm_temperature,
            )
        else:
            try:
                from langchain_openai import ChatOpenAI
            except ImportError:
                raise RuntimeError(
                    "langchain-openai is not installed. "
                    "Add 'langchain-openai' to requirements.api.txt and rebuild the Docker image."
                )

            api_key = settings.require_openai_api_key()

            logger.info(
                "[LLM] Using OpenAI model=%s, api_key_set=%s, temperature=%s, max_tokens=%s",
                settings.openai_model,
                bool(api_key),
                settings.llm_temperature,
                settings.llm_max_tokens,
            )
            self._llm = ChatOpenAI(
                model_name=settings.openai_model,
                openai_api_key=SecretStr(api_key),
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                request_timeout=300.0,
            )

        self._provider = settings.llm_provider
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens
        logger.info("[LLM] LLMService initialized successfully")

        # ── LLM Recording / Mock Playback ─────────────────────────────
        from graph_kb_api.core.llm_recorder import LLMRecorder

        self._recorder = LLMRecorder.from_settings()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        """Return the current model name."""
        if self._provider == "ollama":
            return getattr(self._llm, "model", "unknown")
        return getattr(self._llm, "model_name", "unknown")

    @property
    def llm(self) -> BaseChatModel:
        """Backwards compatibility: expose underlying LLM."""
        return self._llm

    def bind_tools(
        self,
        tools: Any,
        tool_choice: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        """Bind tools so invocations flow through LLMService._agenerate().

        Converts tools to the provider's API format and returns a RunnableBinding
        wrapping *self*, so ``ainvoke`` calls route through our retry/recording
        logic with formatted tools forwarded to the underlying provider.
        """
        formatted_tools = [convert_to_openai_tool(t) for t in tools]
        bind_kwargs: dict[str, Any] = {"tools": formatted_tools, **kwargs}
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return RunnableBinding(bound=self, kwargs=bind_kwargs)

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def set_model(self, model: str) -> None:
        """Hot-swap the underlying chat model without restarting the service.

        Only supported for the OpenAI provider. For Ollama, update the
        OLLAMA_MODEL env var and restart.
        """
        if self._provider == "ollama":
            logger.warning("[LLM] Model hot-swap not supported for Ollama provider")
            return

        from langchain_openai import ChatOpenAI

        api_key = settings.require_openai_api_key()
        logger.info("[LLM] Switching model from %s to %s", self.model_name, model)
        self._llm = ChatOpenAI(
            model_name=model,
            openai_api_key=SecretStr(api_key),
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            request_timeout=300.0,
        )
        logger.info("[LLM] Model switched to %s", model)

    def set_temperature(self, temperature: float) -> None:
        """Update the sampling temperature on the active model."""
        self._temperature = temperature
        if hasattr(self._llm, "temperature"):
            self._llm.temperature = temperature
            logger.info("[LLM] Temperature updated to %s", temperature)

    # ------------------------------------------------------------------
    # BaseChatModel interface with retry logic
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate with retry logic. Implements BaseChatModel._generate."""
        from graph_kb_api.core.llm_recorder import _llm_call_context

        ctx_info = _llm_call_context.get() or {}
        step, phase = ctx_info.get("step", ""), ctx_info.get("phase", "")

        # Mock playback: return pre-recorded response without calling real LLM
        if self._recorder.should_mock:
            mock_msg = self._recorder.get_mock_ai_message(step, phase)
            if mock_msg is not None:
                generation = ChatGeneration(message=cast(BaseMessage, mock_msg))
                return ChatResult(generations=[generation])

        last_error: Optional[Exception] = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response: AIMessage = self.llm.invoke(messages, stop=stop, **kwargs)

                # Record the call
                if self._recorder.should_record:
                    self._recorder.record_call(messages, response, step=step, phase=phase)

                # Wrap in ChatResult format
                generation = ChatGeneration(message=cast(BaseMessage, response))
                return ChatResult(generations=[generation])
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    import time

                    time.sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER

        logger.error("LLM call failed after %d retries: %s", MAX_RETRIES, last_error)
        raise last_error  # type: ignore[misc]

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generate with retry logic. Implements BaseChatModel._agenerate."""
        from graph_kb_api.core.llm_recorder import _llm_call_context

        ctx_info = _llm_call_context.get() or {}
        step, phase = ctx_info.get("step", ""), ctx_info.get("phase", "")

        # Mock playback: return pre-recorded response without calling real LLM
        if self._recorder.should_mock:
            mock_msg = self._recorder.get_mock_ai_message(step, phase)
            if mock_msg is not None:
                generation = ChatGeneration(message=cast(BaseMessage, mock_msg))
                return ChatResult(generations=[generation])

        last_error: Optional[Exception] = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._llm.ainvoke(messages, stop=stop, **kwargs)

                # Record the call
                if self._recorder.should_record:
                    self._recorder.record_call(messages, response, step=step, phase=phase)

                # Wrap in ChatResult format
                generation = ChatGeneration(message=cast(BaseMessage, response))
                return ChatResult(generations=[generation])
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Async LLM call attempt %d/%d failed: %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER

        logger.error("Async LLM call failed after %d retries: %s", MAX_RETRIES, last_error)
        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Convenience methods (backwards compatibility)
    # ------------------------------------------------------------------

    def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a response from prompts, retrying on transient failures."""
        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response: AIMessage = self.invoke(messages)
        return str(response.content)

    async def a_generate_response(self, system_prompt: str, user_prompt: str) -> str:
        """Async generate from prompts with exponential-backoff retries."""
        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response: AIMessage = await self.ainvoke(messages)
        return str(response.content)
