"""
Unit tests for the NaturalLanguageHandler routing chain.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graph_kb_api.core.nl_router import NaturalLanguageHandler, RouteResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.a_generate_response = AsyncMock(return_value="Fallback QA answer")
    return llm


@pytest.fixture
def mock_facade():
    facade = MagicMock()
    retrieval_result = MagicMock()
    retrieval_result.context_items = []
    facade.retrieval_service.retrieve.return_value = retrieval_result
    return facade


@pytest.fixture
def handler(mock_llm, mock_facade):
    return NaturalLanguageHandler(llm_service=mock_llm, facade=mock_facade)


@pytest.fixture
def progress():
    return AsyncMock()


# ---------------------------------------------------------------------------
# RouteResult dataclass
# ---------------------------------------------------------------------------


class TestRouteResult:
    def test_defaults(self):
        r = RouteResult(success=True, source="qa_handler")
        assert r.response == ""
        assert r.context_items == []
        assert r.mermaid_code is None
        assert r.intent_result is None


# ---------------------------------------------------------------------------
# Routing order: Deep Agent → IntentDetector → QA Handler
# ---------------------------------------------------------------------------


class TestRoutingOrder:
    """Req 9.1, 9.2, 9.3, 9.4 — strict fallback ordering."""

    async def test_deep_agent_success_returns_immediately(self, handler, progress):
        """Req 9.1 — Deep Agent is tried first."""
        with patch(
            "graph_kb_api.core.nl_router.NaturalLanguageHandler._try_deep_agent",
            new_callable=AsyncMock,
            return_value=RouteResult(
                success=True, source="deep_agent", response="deep answer"
            ),
        ) as mock_deep:
            result = await handler.route(
                "explain auth", "repo1", progress_callback=progress
            )

        assert result.source == "deep_agent"
        assert result.response == "deep answer"
        mock_deep.assert_awaited_once()

    async def test_falls_to_intent_when_deep_agent_fails(self, handler, progress):
        """Req 9.2 — falls to IntentDetector when Deep Agent fails."""
        with (
            patch(
                "graph_kb_api.core.nl_router.NaturalLanguageHandler._try_deep_agent",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "graph_kb_api.core.nl_router.NaturalLanguageHandler._try_intent_detector",
                new_callable=AsyncMock,
                return_value=RouteResult(
                    success=True, source="intent_detector", response="intent matched"
                ),
            ) as mock_intent,
        ):
            result = await handler.route(
                "list repos", "repo1", progress_callback=progress
            )

        assert result.source == "intent_detector"
        mock_intent.assert_awaited_once()

    async def test_falls_to_qa_when_intent_low_confidence(
        self, handler, mock_llm, progress
    ):
        """Req 9.3 — falls to QA when IntentDetector confidence < 0.7."""
        with (
            patch(
                "graph_kb_api.core.nl_router.NaturalLanguageHandler._try_deep_agent",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "graph_kb_api.core.nl_router.NaturalLanguageHandler._try_intent_detector",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_llm.a_generate_response.return_value = "QA fallback answer"
            result = await handler.route(
                "vague question", "repo1", progress_callback=progress
            )

        assert result.source == "qa_handler"
        assert result.success is True

    async def test_full_chain_order_deep_intent_qa(self, handler, mock_llm, progress):
        """Req 9.4 — ordering is Deep_Agent → IntentDetector → QA_Handler."""
        call_order = []

        async def mock_deep(*a, **kw):
            call_order.append("deep_agent")
            return None

        async def mock_intent(*a, **kw):
            call_order.append("intent_detector")
            return None

        original_qa = handler._qa_handler

        async def mock_qa(*a, **kw):
            call_order.append("qa_handler")
            return await original_qa(*a, **kw)

        handler._try_deep_agent = mock_deep
        handler._try_intent_detector = mock_intent
        handler._qa_handler = mock_qa

        await handler.route("anything", "repo1", progress_callback=progress)

        assert call_order == ["deep_agent", "intent_detector", "qa_handler"]


# ---------------------------------------------------------------------------
# Deep Agent tier
# ---------------------------------------------------------------------------


class TestDeepAgentTier:
    async def test_returns_none_when_facade_missing(self, mock_llm, progress):
        h = NaturalLanguageHandler(llm_service=mock_llm, facade=None)
        result = await h._try_deep_agent("q", "r", progress)
        assert result is None

    async def test_returns_none_on_import_error(self, handler, progress):
        # Simulate ImportError by patching builtins.__import__
        original_import = (
            __builtins__.__import__
            if hasattr(__builtins__, "__import__")
            else __import__
        )

        def fail_import(name, *args, **kwargs):
            if "ask_code" in name:
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            result = await handler._try_deep_agent("q", "r", progress)
        assert result is None

    async def test_returns_none_on_empty_response(self, handler, progress):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(return_value={"final_output": ""})
        mock_module = MagicMock()
        mock_module.AskCodeWorkflowEngine = MagicMock(return_value=mock_engine)
        with patch.dict(
            "sys.modules",
            {"graph_kb_api.flows.v3.graphs.ask_code": mock_module},
        ):
            result = await handler._try_deep_agent("q", "r", progress)
        assert result is None

    async def test_returns_result_on_success(self, handler, progress):
        mock_engine = MagicMock()
        mock_engine.run = AsyncMock(
            return_value={
                "final_output": "deep answer",
                "context_items": [{"file_path": "a.py"}],
                "mermaid_code": "graph TD; A-->B",
            }
        )
        mock_module = MagicMock()
        mock_module.AskCodeWorkflowEngine = MagicMock(return_value=mock_engine)
        with patch.dict(
            "sys.modules",
            {"graph_kb_api.flows.v3.graphs.ask_code": mock_module},
        ):
            result = await handler._try_deep_agent("q", "r", progress)
        assert result is not None
        assert result.success is True
        assert result.source == "deep_agent"
        assert result.response == "deep answer"
        assert result.mermaid_code == "graph TD; A-->B"


# ---------------------------------------------------------------------------
# Intent Detector tier
# ---------------------------------------------------------------------------


class TestIntentDetectorTier:
    async def test_returns_none_below_threshold(self, handler, mock_llm, progress):
        mock_llm.a_generate_response.return_value = json.dumps(
            {"intent": "ask_code", "confidence": 0.4, "params": {}}
        )
        result = await handler._try_intent_detector("vague", progress)
        assert result is None

    async def test_returns_result_above_threshold(self, handler, mock_llm, progress):
        mock_llm.a_generate_response.return_value = json.dumps(
            {"intent": "list_repos", "confidence": 0.9, "params": {}}
        )
        result = await handler._try_intent_detector("show repos", progress)
        assert result is not None
        assert result.success is True
        assert result.source == "intent_detector"
        assert result.intent_result.intent == "list_repos"

    async def test_returns_none_on_exception(self, handler, mock_llm, progress):
        mock_llm.a_generate_response.side_effect = RuntimeError("boom")
        result = await handler._try_intent_detector("anything", progress)
        assert result is None


# ---------------------------------------------------------------------------
# QA Handler tier
# ---------------------------------------------------------------------------


class TestQAHandlerTier:
    async def test_returns_llm_response(self, handler, mock_llm, progress):
        mock_llm.a_generate_response.return_value = "Here is the answer"
        result = await handler._qa_handler("question", "repo1", progress)
        assert result.success is True
        assert result.source == "qa_handler"
        assert result.response == "Here is the answer"

    async def test_includes_context_items(
        self, handler, mock_llm, mock_facade, progress
    ):
        item = MagicMock()
        item.file_path = "src/main.py"
        item.content = "def main(): pass"
        item.score = 0.95
        retrieval_result = MagicMock()
        retrieval_result.context_items = [item]
        mock_facade.retrieval_service.retrieve.return_value = retrieval_result

        mock_llm.a_generate_response.return_value = "answer with context"
        result = await handler._qa_handler("question", "repo1", progress)
        assert len(result.context_items) == 1
        assert result.context_items[0]["file_path"] == "src/main.py"

    async def test_handles_llm_failure_gracefully(self, handler, mock_llm, progress):
        mock_llm.a_generate_response.side_effect = RuntimeError("LLM down")
        result = await handler._qa_handler("question", "repo1", progress)
        assert result.success is False
        assert result.source == "qa_handler"
        assert "unable to process" in result.response.lower()

    async def test_works_without_facade(self, mock_llm, progress):
        h = NaturalLanguageHandler(llm_service=mock_llm, facade=None)
        mock_llm.a_generate_response.return_value = "no context answer"
        result = await h._qa_handler("question", "", progress)
        assert result.success is True
        assert result.response == "no context answer"


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


class TestGetNaturalLanguageHandler:
    def test_creates_handler(self, mock_llm):
        import graph_kb_api.core.nl_router as mod
        from graph_kb_api.core.nl_router import get_natural_language_handler

        mod._handler = None  # reset singleton
        h = get_natural_language_handler(llm_service=mock_llm)
        assert isinstance(h, NaturalLanguageHandler)
        mod._handler = None  # cleanup
