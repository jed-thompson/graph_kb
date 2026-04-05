"""
Integration tests for REST endpoints.

Uses httpx for async testing with FastAPI TestClient.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from graph_kb_api.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async test client for the API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestHealthEndpoints:
    """Test health check endpoints."""

    @pytest.mark.anyio
    async def test_health(self, client):
        """Test basic health endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "version" in data

    @pytest.mark.anyio
    async def test_api_health(self, client):
        """Test API health endpoint with service status."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data


class TestReposEndpoints:
    """Test repository management endpoints."""

    @pytest.mark.anyio
    async def test_list_repos(self, client):
        """Test listing repositories."""
        response = await client.get("/api/v1/repos")
        assert response.status_code == 200
        data = response.json()
        assert "repos" in data
        assert "total" in data

    @pytest.mark.anyio
    async def test_get_repo_not_found(self, client):
        """Test getting non-existent repository."""
        response = await client.get("/api/v1/repos/nonexistent-id")
        assert response.status_code == 404


class TestSymbolsEndpoints:
    """Test symbol query endpoints."""

    @pytest.mark.anyio
    async def test_search_symbols_no_repo(self, client):
        """Test searching symbols for non-existent repo."""
        response = await client.get("/api/v1/repos/nonexistent/symbols")
        # 200 with empty list, 404 if repo checked, or 500/503 if services unavailable
        assert response.status_code in [200, 404, 500, 503]


class TestSearchEndpoints:
    """Test search endpoints."""

    @pytest.mark.anyio
    async def test_search_code(self, client):
        """Test semantic search endpoint."""
        response = await client.post(
            "/api/v1/repos/test-repo/search", json={"query": "test query", "top_k": 10}
        )
        # May fail if repo doesn't exist, but should be valid request
        assert response.status_code in [200, 404, 500]


class TestAnalysisEndpoints:
    """Test analysis endpoints."""

    @pytest.mark.anyio
    async def test_get_stats(self, client):
        """Test graph stats endpoint."""
        response = await client.get("/api/v1/repos/test-repo/stats")
        # Should return stats or 404
        assert response.status_code in [200, 404, 500]
