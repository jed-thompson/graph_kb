"""
Unit tests for the IntentDetector class.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.core.intent_detector import IntentDetector
from graph_kb_api.schemas.intent import IntentConfig, IntentResult


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.a_generate_response = AsyncMock()
    return llm


@pytest.fixture
def detector(mock_llm):
    return IntentDetector(llm=mock_llm)


# ---------------------------------------------------------------------------
# Class constants
# ---------------------------------------------------------------------------


class TestIntentDetectorConstants:
    def test_has_exactly_17_intents(self):
        assert len(IntentDetector.INTENTS) == 17

    def test_all_required_intents_present(self):
        expected = {
            "ingest_repo",
            "check_diff",
            "list_repos",
            "check_status",
            "upload_docs",
            "list_docs",
            "view_doc",
            "delete_doc",
            "generate_spec",
            "generate_doc",
            "add_template",
            "add_steering",
            "list_steering",
            "remove_steering",
            "show_menu",
            "get_help",
            "ask_code",
        }
        assert set(IntentDetector.INTENTS) == expected

    def test_confidence_threshold(self):
        assert IntentDetector.CONFIDENCE_THRESHOLD == 0.7

    def test_every_intent_has_config(self):
        for intent in IntentDetector.INTENTS:
            assert intent in IntentDetector.INTENT_CONFIGS
            cfg = IntentDetector.INTENT_CONFIGS[intent]
            assert isinstance(cfg, IntentConfig)


# ---------------------------------------------------------------------------
# detect() method
# ---------------------------------------------------------------------------


class TestDetect:
    async def test_returns_intent_result(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "list_repos",
                "confidence": 0.95,
                "params": {},
            }
        )
        result = await detector.detect("show me all repos")
        assert isinstance(result, IntentResult)
        assert result.intent == "list_repos"
        assert result.confidence == 0.95
        assert result.params == {}

    async def test_extracts_params(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "ingest_repo",
                "confidence": 0.9,
                "params": {"url": "https://github.com/org/repo", "branch": "main"},
            }
        )
        result = await detector.detect("ingest https://github.com/org/repo on main")
        assert result.intent == "ingest_repo"
        assert result.params["url"] == "https://github.com/org/repo"
        assert result.params["branch"] == "main"

    async def test_high_confidence_above_threshold(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "get_help",
                "confidence": 0.85,
                "params": {},
            }
        )
        result = await detector.detect("help me")
        assert result.confidence >= IntentDetector.CONFIDENCE_THRESHOLD

    async def test_low_confidence_below_threshold(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "ask_code",
                "confidence": 0.4,
                "params": {},
            }
        )
        result = await detector.detect("something vague")
        assert result.confidence < IntentDetector.CONFIDENCE_THRESHOLD

    async def test_unknown_intent_falls_back_to_ask_code(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "unknown_intent",
                "confidence": 0.8,
                "params": {},
            }
        )
        result = await detector.detect("do something weird")
        assert result.intent == "ask_code"

    async def test_confidence_clamped_to_max_1(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "list_repos",
                "confidence": 1.5,
                "params": {},
            }
        )
        result = await detector.detect("list repos")
        assert result.confidence == 1.0

    async def test_confidence_clamped_to_min_0(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = json.dumps(
            {
                "intent": "list_repos",
                "confidence": -0.3,
                "params": {},
            }
        )
        result = await detector.detect("list repos")
        assert result.confidence == 0.0

    async def test_llm_error_returns_low_confidence(self, detector, mock_llm):
        mock_llm.a_generate_response.side_effect = RuntimeError("LLM down")
        result = await detector.detect("anything")
        assert result.intent == "ask_code"
        assert result.confidence == 0.0
        assert result.params == {}

    async def test_malformed_json_returns_low_confidence(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = "not json at all"
        result = await detector.detect("anything")
        assert result.confidence == 0.0

    async def test_handles_markdown_code_fence(self, detector, mock_llm):
        mock_llm.a_generate_response.return_value = (
            '```json\n{"intent": "show_menu", "confidence": 0.9, "params": {}}\n```'
        )
        result = await detector.detect("show menu")
        assert result.intent == "show_menu"
        assert result.confidence == 0.9


# ---------------------------------------------------------------------------
# get_config()
# ---------------------------------------------------------------------------


class TestGetConfig:
    def test_known_intent(self, detector):
        cfg = detector.get_config("ingest_repo")
        assert cfg.handler == "/ingest"
        assert "url" in cfg.required_params

    def test_unknown_intent_returns_default(self, detector):
        cfg = detector.get_config("nonexistent")
        assert cfg.handler == "/ask_code"


# ---------------------------------------------------------------------------
# _parse_response()
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_plain_json(self):
        raw = '{"intent": "list_repos", "confidence": 0.9, "params": {}}'
        result = IntentDetector._parse_response(raw)
        assert result["intent"] == "list_repos"

    def test_markdown_fenced_json(self):
        raw = '```json\n{"intent": "get_help", "confidence": 0.8, "params": {}}\n```'
        result = IntentDetector._parse_response(raw)
        assert result["intent"] == "get_help"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            IntentDetector._parse_response("not json")
