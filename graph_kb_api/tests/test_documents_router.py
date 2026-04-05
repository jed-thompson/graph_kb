"""
Unit tests for the documents router.

Tests the four document endpoints using mocked facade/vector store dependencies.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.graph_kb.storage.vector_store import SearchResult
from graph_kb_api.routers.documents import router as documents_router

# Build a minimal app with just the documents router for isolated testing
_test_app = FastAPI()
_test_app.include_router(documents_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_facade(vector_store=None, embedding_generator=None):
    facade = MagicMock()
    facade.vector_store = vector_store
    facade.embedding_generator = embedding_generator
    return facade


def _make_vector_store(collection_data=None, get_result=None):
    vs = MagicMock()
    collection = MagicMock()
    if collection_data is not None:
        collection.get.return_value = collection_data
    else:
        collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    vs.collection = collection
    vs.get.return_value = get_result
    return vs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_vector_store():
    return _make_vector_store()


@pytest.fixture
def mock_embedding_generator():
    eg = MagicMock()
    eg.embed.return_value = [0.1] * 768
    return eg


@pytest.fixture
def mock_facade(mock_vector_store, mock_embedding_generator):
    return _make_facade(mock_vector_store, mock_embedding_generator)


@pytest.fixture
async def client(mock_facade):
    _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/docs — list documents
# ---------------------------------------------------------------------------


class TestListDocuments:
    @pytest.mark.anyio
    async def test_list_empty(self, client, mock_vector_store):
        response = await client.get("/api/v1/docs")
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == []
        assert data["total"] == 0
        assert data["offset"] == 0
        assert data["limit"] == 50

    @pytest.mark.anyio
    async def test_list_with_results(self, client, mock_vector_store):
        mock_vector_store.collection.get.return_value = {
            "ids": ["doc-1"],
            "metadatas": [
                {"filename": "readme.md", "created_at": "2024-01-01T00:00:00"}
            ],
            "documents": ["# Hello"],
        }
        response = await client.get("/api/v1/docs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["documents"][0]["id"] == "doc-1"
        assert data["documents"][0]["filename"] == "readme.md"

    @pytest.mark.anyio
    async def test_list_with_parent_filter(self, client, mock_vector_store):
        mock_vector_store.collection.get.return_value = {
            "ids": ["doc-2"],
            "metadatas": [
                {
                    "filename": "child.md",
                    "parent": "root",
                    "created_at": "2024-01-01T00:00:00",
                }
            ],
            "documents": ["child content"],
        }
        response = await client.get("/api/v1/docs?parent=root")
        assert response.status_code == 200
        call_kwargs = mock_vector_store.collection.get.call_args
        assert call_kwargs[1].get("where") == {"parent": "root"}

    @pytest.mark.anyio
    async def test_list_pagination(self, client, mock_vector_store):
        mock_vector_store.collection.get.return_value = {
            "ids": ["d1", "d2", "d3"],
            "metadatas": [
                {"filename": "a.md", "created_at": "2024-01-01T00:00:00"},
                {"filename": "b.md", "created_at": "2024-01-01T00:00:00"},
                {"filename": "c.md", "created_at": "2024-01-01T00:00:00"},
            ],
            "documents": ["a", "b", "c"],
        }
        response = await client.get("/api/v1/docs?offset=1&limit=1")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["documents"]) == 1
        assert data["documents"][0]["id"] == "d2"

    @pytest.mark.anyio
    async def test_list_503_when_vector_store_unavailable(self, mock_facade):
        mock_facade.vector_store = None
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/api/v1/docs")
        _test_app.dependency_overrides.clear()
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/v1/docs/{doc_id} — get document
# ---------------------------------------------------------------------------


class TestGetDocument:
    @pytest.mark.anyio
    async def test_get_existing(self, client, mock_vector_store):
        mock_vector_store.get.return_value = SearchResult(
            chunk_id="doc-1",
            score=1.0,
            metadata={"filename": "readme.md", "created_at": "2024-01-01T00:00:00"},
            content="# Hello",
        )
        response = await client.get("/api/v1/docs/doc-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "doc-1"
        assert data["content"] == "# Hello"

    @pytest.mark.anyio
    async def test_get_not_found(self, client, mock_vector_store):
        mock_vector_store.get.return_value = None
        response = await client.get("/api/v1/docs/nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/docs/upload — upload document
# ---------------------------------------------------------------------------


class TestUploadDocument:
    @pytest.mark.anyio
    async def test_upload_new(
        self, client, mock_vector_store, mock_embedding_generator
    ):
        # No existing doc
        mock_vector_store.collection.get.return_value = {
            "ids": [],
            "metadatas": [],
            "documents": [],
        }
        response = await client.post(
            "/api/v1/docs/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.txt"
        assert data["content"] == "hello world"
        assert data["id"]  # uuid generated
        mock_vector_store.upsert.assert_called_once()
        mock_embedding_generator.embed.assert_called_once_with("hello world")

    @pytest.mark.anyio
    async def test_upload_skip_existing(self, client, mock_vector_store):
        mock_vector_store.collection.get.return_value = {
            "ids": ["existing-id"],
            "metadatas": [
                {"filename": "test.txt", "created_at": "2024-01-01T00:00:00"}
            ],
            "documents": ["old content"],
        }
        response = await client.post(
            "/api/v1/docs/upload",
            files={"file": ("test.txt", b"new content", "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "existing-id"
        mock_vector_store.upsert.assert_not_called()

    @pytest.mark.anyio
    async def test_upload_force(
        self, client, mock_vector_store, mock_embedding_generator
    ):
        response = await client.post(
            "/api/v1/docs/upload",
            files={"file": ("test.txt", b"forced content", "text/plain")},
            data={"force": "true"},
        )
        assert response.status_code == 200
        mock_vector_store.upsert.assert_called_once()

    @pytest.mark.anyio
    async def test_upload_with_parent(
        self, client, mock_vector_store, mock_embedding_generator
    ):
        mock_vector_store.collection.get.return_value = {
            "ids": [],
            "metadatas": [],
            "documents": [],
        }
        response = await client.post(
            "/api/v1/docs/upload",
            files={"file": ("child.md", b"content", "text/plain")},
            data={"parent": "root-doc"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["parent"] == "root-doc"


# ---------------------------------------------------------------------------
# DELETE /api/v1/docs/{doc_id} — delete document
# ---------------------------------------------------------------------------


class TestDeleteDocument:
    @pytest.mark.anyio
    async def test_delete_success(self, client, mock_vector_store):
        response = await client.delete("/api/v1/docs/doc-1")
        assert response.status_code == 204
        mock_vector_store.delete.assert_called_once_with("doc-1")

    @pytest.mark.anyio
    async def test_delete_503_when_unavailable(self, mock_facade):
        mock_facade.vector_store = None
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.delete("/api/v1/docs/doc-1")
        _test_app.dependency_overrides.clear()
        assert response.status_code == 503
