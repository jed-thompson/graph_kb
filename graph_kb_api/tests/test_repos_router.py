"""
Unit tests for the repos router.

Tests list, get, and delete endpoints using a mocked facade
with in-memory metadata store. Follows the same pattern as
test_settings_router.py.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.routers.repos import router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(
    repo_id="repo-1",
    git_url="https://github.com/org/repo",
    default_branch="main",
    last_indexed_at=None,
    last_indexed_commit=None,
    status="ready",
    error_message=None,
):
    """Create a lightweight domain-like repo object."""
    status_obj = SimpleNamespace(value=status)
    return SimpleNamespace(
        repo_id=repo_id,
        git_url=git_url,
        default_branch=default_branch,
        last_indexed_at=last_indexed_at,
        last_indexed_commit=last_indexed_commit,
        status=status_obj,
        error_message=error_message,
    )


class FakeMetadataStore:
    """In-memory metadata store for testing repos router."""

    def __init__(self, repos=None):
        self._repos = {r.repo_id: r for r in (repos or [])}

    def list_repos(self):
        return list(self._repos.values())

    def get_repository(self, repo_id):
        return self._repos.get(repo_id)

    def delete_repository(self, repo_id):
        return self._repos.pop(repo_id, None) is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_facade():
    facade = MagicMock()
    facade.metadata_store = FakeMetadataStore()
    facade.graph_store = MagicMock()
    facade.vector_store = MagicMock()
    return facade


@pytest.fixture
def repos_app(fake_facade):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_kb_facade] = lambda: fake_facade
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(repos_app):
    transport = ASGITransport(app=repos_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# List repos
# ---------------------------------------------------------------------------


class TestListRepos:
    """GET /repos"""

    @pytest.mark.anyio
    async def test_empty_list(self, client):
        resp = await client.get("/repos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repos"] == []
        assert data["total"] == 0

    @pytest.mark.anyio
    async def test_returns_repos(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1", git_url="https://github.com/a/b"),
                _make_repo(
                    repo_id="r2", git_url="https://github.com/c/d", status="indexing"
                ),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["repos"]) == 2
        ids = {r["id"] for r in data["repos"]}
        assert ids == {"r1", "r2"}

    @pytest.mark.anyio
    async def test_filter_by_status(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1", status="ready"),
                _make_repo(repo_id="r2", status="error"),
                _make_repo(repo_id="r3", status="ready"),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos", params={"status": "ready"})

        data = resp.json()
        assert data["total"] == 2
        assert all(r["status"] == "ready" for r in data["repos"])

    @pytest.mark.anyio
    async def test_pagination(self, fake_facade, repos_app):
        repos = [_make_repo(repo_id=f"r{i}") for i in range(5)]
        fake_facade.metadata_store = FakeMetadataStore(repos)
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos", params={"offset": 2, "limit": 2})

        data = resp.json()
        assert data["total"] == 5
        assert len(data["repos"]) == 2
        assert data["offset"] == 2
        assert data["limit"] == 2

    @pytest.mark.anyio
    async def test_metadata_store_none_returns_empty(self, fake_facade, repos_app):
        fake_facade.metadata_store = None
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos")

        assert resp.status_code == 200
        assert resp.json()["repos"] == []


# ---------------------------------------------------------------------------
# Get repo
# ---------------------------------------------------------------------------


class TestGetRepo:
    """GET /repos/{repo_id}"""

    @pytest.mark.anyio
    async def test_returns_repo(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1", git_url="https://github.com/a/b"),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos/r1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "r1"
        assert data["git_url"] == "https://github.com/a/b"
        assert data["status"] == "ready"

    @pytest.mark.anyio
    async def test_404_when_not_found(self, client):
        resp = await client.get("/repos/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_404_when_metadata_store_none(self, fake_facade, repos_app):
        fake_facade.metadata_store = None
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/repos/any-id")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete repo
# ---------------------------------------------------------------------------


class TestDeleteRepo:
    """DELETE /repos/{repo_id}"""

    @pytest.mark.anyio
    async def test_delete_returns_204(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1"),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete("/repos/r1")

        assert resp.status_code == 204

    @pytest.mark.anyio
    async def test_delete_calls_all_stores(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1"),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.delete("/repos/r1")

        fake_facade.graph_store.delete_repository.assert_called_once_with("r1")
        fake_facade.vector_store.delete_repository.assert_called_once_with("r1")

    @pytest.mark.anyio
    async def test_delete_404_when_not_found(self, client):
        resp = await client.delete("/repos/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_with_error_repo(self, fake_facade, repos_app):
        fake_facade.metadata_store = FakeMetadataStore(
            [
                _make_repo(repo_id="r1", status="error", error_message="boom"),
            ]
        )
        transport = ASGITransport(app=repos_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete("/repos/r1")

        assert resp.status_code == 204
