"""
Unit tests for the chat/LLM router.

Tests the POST /ask and POST /ask/stream endpoints using mocked
facade, retrieval service, and LLM service.
"""

import json
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.routers.chat import extract_mermaid_diagrams, router

_test_app = FastAPI()
_test_app.include_router(router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Lightweight stubs for retrieval models
# ---------------------------------------------------------------------------


@dataclass
class FakeContextItem:
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    content: Optional[str] = None
    symbol: Optional[str] = None
    score: Optional[float] = None


@dataclass
class FakeRetrievalResponse:
    context_items: List[FakeContextItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_context_items():
    return [
        FakeContextItem(
            file_path="src/main.py",
            start_line=1,
            end_line=10,
            content="def main():\n    pass",
            symbol="main",
            score=0.95,
        ),
    ]


def _make_retrieval_service(context_items=None):
    svc = MagicMock()
    svc.retrieve.return_value = FakeRetrievalResponse(context_items=context_items or [])
    return svc


def _make_facade(retrieval_service=None):
    facade = MagicMock()
    facade.retrieval_service = retrieval_service
    return facade


def _valid_request():
    return {
        "repo_id": "test-repo",
        "query": "What does the main function do?",
        "top_k": 10,
        "max_depth": 3,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_retrieval_service():
    return _make_retrieval_service(_sample_context_items())


@pytest.fixture
def mock_facade(mock_retrieval_service):
    return _make_facade(retrieval_service=mock_retrieval_service)


@pytest.fixture
async def client(mock_facade):
    _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# extract_mermaid_diagrams tests
# ---------------------------------------------------------------------------


class TestExtractMermaidDiagrams:
    def test_no_diagrams(self):
        assert extract_mermaid_diagrams("Hello world") == []

    def test_single_diagram(self):
        text = "Some text\n```mermaid\ngraph TD\n  A-->B\n```\nMore text"
        diagrams = extract_mermaid_diagrams(text)
        assert len(diagrams) == 1
        assert "graph TD" in diagrams[0]

    def test_multiple_diagrams(self):
        text = (
            "```mermaid\ngraph LR\n  A-->B\n```\n"
            "middle\n"
            "```mermaid\nsequenceDiagram\n  A->>B: Hi\n```"
        )
        diagrams = extract_mermaid_diagrams(text)
        assert len(diagrams) == 2

    def test_non_mermaid_code_blocks_ignored(self):
        text = "```python\nprint('hi')\n```\n```mermaid\ngraph TD\n```"
        diagrams = extract_mermaid_diagrams(text)
        assert len(diagrams) == 1


# ---------------------------------------------------------------------------
# POST /ask tests
# ---------------------------------------------------------------------------


class TestAskCode:
    @pytest.mark.anyio
    @patch("graph_kb_api.core.llm.LLMService")
    async def test_success_returns_answer_and_sources(
        self, MockLLMService, client, mock_facade
    ):
        mock_llm = MagicMock()
        mock_llm.a_generate_response = AsyncMock(
            return_value="The main function initialises the app."
        )
        mock_llm.llm = MagicMock()
        mock_llm.llm.model_name = "gpt-4o"
        MockLLMService.return_value = mock_llm

        resp = await client.post("/api/v1/chat/ask", json=_valid_request())
        assert resp.status_code == 200
        data = resp.json()
        assert "main function" in data["answer"]
        assert len(data["sources"]) == 1
        assert data["sources"][0]["file_path"] == "src/main.py"

    @pytest.mark.anyio
    @patch("graph_kb_api.core.llm.LLMService")
    async def test_mermaid_diagrams_extracted(
        self, MockLLMService, client, mock_facade
    ):
        answer_with_mermaid = (
            "Here is the architecture:\n```mermaid\ngraph TD\n  A-->B\n```\nThat's it."
        )
        mock_llm = MagicMock()
        mock_llm.a_generate_response = AsyncMock(return_value=answer_with_mermaid)
        mock_llm.llm = MagicMock()
        mock_llm.llm.model_name = "gpt-4o"
        MockLLMService.return_value = mock_llm

        resp = await client.post("/api/v1/chat/ask", json=_valid_request())
        data = resp.json()
        assert len(data["mermaid_diagrams"]) == 1
        assert "graph TD" in data["mermaid_diagrams"][0]

    @pytest.mark.anyio
    async def test_no_context_returns_acknowledgement(self, mock_facade):
        # Retrieval returns empty
        mock_facade.retrieval_service.retrieve.return_value = FakeRetrievalResponse(
            context_items=[]
        )
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/v1/chat/ask", json=_valid_request())
        _test_app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert (
            "couldn't find" in data["answer"].lower() or "no" in data["answer"].lower()
        )
        assert data["sources"] == []

    @pytest.mark.anyio
    @patch("graph_kb_api.core.llm.LLMService")
    async def test_llm_unreachable_returns_502(
        self, MockLLMService, client, mock_facade
    ):
        MockLLMService.side_effect = Exception("Connection refused")

        resp = await client.post("/api/v1/chat/ask", json=_valid_request())
        assert resp.status_code == 502

    @pytest.mark.anyio
    async def test_retrieval_service_unavailable_returns_503(self):
        facade = _make_facade(retrieval_service=None)
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/v1/chat/ask", json=_valid_request())
        _test_app.dependency_overrides.clear()
        assert resp.status_code == 503

    @pytest.mark.anyio
    async def test_validation_empty_query_returns_422(self, client):
        req = _valid_request()
        req["query"] = ""
        resp = await client.post("/api/v1/chat/ask", json=req)
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_validation_top_k_out_of_range_returns_422(self, client):
        req = _valid_request()
        req["top_k"] = 200
        resp = await client.post("/api/v1/chat/ask", json=req)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /ask/stream tests
# ---------------------------------------------------------------------------


class TestAskCodeStream:
    @pytest.mark.anyio
    @patch("graph_kb_api.core.llm.LLMService")
    async def test_stream_returns_sse_content_type(
        self, MockLLMService, client, mock_facade
    ):
        # Set up a mock LLM that yields chunks
        mock_llm = MagicMock()

        async def _fake_astream(messages):
            for token in ["Hello", " world"]:
                chunk = MagicMock()
                chunk.content = token
                yield chunk

        mock_llm.llm = MagicMock()
        mock_llm.llm.astream = _fake_astream
        MockLLMService.return_value = mock_llm

        resp = await client.post("/api/v1/chat/ask/stream", json=_valid_request())
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @pytest.mark.anyio
    @patch("graph_kb_api.core.llm.LLMService")
    async def test_stream_contains_sources_and_chunks(
        self, MockLLMService, client, mock_facade
    ):
        mock_llm = MagicMock()

        async def _fake_astream(messages):
            for token in ["The ", "answer"]:
                chunk = MagicMock()
                chunk.content = token
                yield chunk

        mock_llm.llm = MagicMock()
        mock_llm.llm.astream = _fake_astream
        MockLLMService.return_value = mock_llm

        resp = await client.post("/api/v1/chat/ask/stream", json=_valid_request())
        body = resp.text

        # Parse SSE events
        events = []
        for line in body.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # First event should be sources
        assert events[0]["type"] == "sources"
        assert len(events[0]["sources"]) == 1

        # Should have chunk events
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1

        # Last event should be done
        assert events[-1]["type"] == "done"

    @pytest.mark.anyio
    async def test_stream_no_context_returns_acknowledgement(self, mock_facade):
        mock_facade.retrieval_service.retrieve.return_value = FakeRetrievalResponse(
            context_items=[]
        )
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/api/v1/chat/ask/stream", json=_valid_request())
        _test_app.dependency_overrides.clear()

        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert any("couldn't find" in e["content"].lower() for e in chunk_events)
