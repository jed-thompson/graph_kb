"""
Unit tests for the steering document router.

Tests all five endpoints: GET /, POST /, GET /{filename},
PUT /{filename}, DELETE /{filename}.
"""

import shutil
import tempfile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.core.steering_manager import SteeringManager
from graph_kb_api.routers.steering import _get_steering_manager, router


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_steering_dir():
    """Create a temporary directory for steering documents."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def steering_app(tmp_steering_dir):
    """Create a test FastAPI app with the steering router and a temp directory."""
    manager = SteeringManager(tmp_steering_dir)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_get_steering_manager] = lambda: manager
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(steering_app):
    transport = ASGITransport(app=steering_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestListSteeringDocs:
    """GET /steering — list all steering documents."""

    @pytest.mark.anyio
    async def test_empty_list(self, client):
        resp = await client.get("/steering")
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"] == []
        assert data["total"] == 0

    @pytest.mark.anyio
    async def test_list_after_upload(self, client):
        # Upload a doc first
        await client.post(
            "/steering",
            files={"file": ("guide.md", b"# Guide\nSome content", "text/markdown")},
        )
        resp = await client.get("/steering")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["documents"][0]["filename"] == "guide.md"


class TestAddSteeringDoc:
    """POST /steering — upload a steering document."""

    @pytest.mark.anyio
    async def test_upload(self, client):
        resp = await client.post(
            "/steering",
            files={"file": ("rules.md", b"Be concise.", "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "rules.md"
        assert data["content"] == "Be concise."
        assert "created_at" in data

    @pytest.mark.anyio
    async def test_upload_adds_md_extension(self, client):
        resp = await client.post(
            "/steering",
            files={"file": ("notes", b"plain text", "text/plain")},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"].endswith(".md")


class TestGetSteeringDoc:
    """GET /steering/{filename} — retrieve a single document."""

    @pytest.mark.anyio
    async def test_get_existing(self, client):
        await client.post(
            "/steering",
            files={"file": ("doc.md", b"Hello world", "text/markdown")},
        )
        resp = await client.get("/steering/doc.md")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Hello world"

    @pytest.mark.anyio
    async def test_get_not_found(self, client):
        resp = await client.get("/steering/nonexistent.md")
        assert resp.status_code == 404


class TestUpdateSteeringDoc:
    """PUT /steering/{filename} — update document content."""

    @pytest.mark.anyio
    async def test_update_existing(self, client):
        await client.post(
            "/steering",
            files={"file": ("edit.md", b"original", "text/markdown")},
        )
        resp = await client.put(
            "/steering/edit.md",
            content="updated content",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "updated content"

        # Verify persistence
        get_resp = await client.get("/steering/edit.md")
        assert get_resp.json()["content"] == "updated content"

    @pytest.mark.anyio
    async def test_update_not_found(self, client):
        resp = await client.put(
            "/steering/missing.md",
            content="new content",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 404


class TestDeleteSteeringDoc:
    """DELETE /steering/{filename} — remove a document."""

    @pytest.mark.anyio
    async def test_delete_existing(self, client):
        await client.post(
            "/steering",
            files={"file": ("bye.md", b"goodbye", "text/markdown")},
        )
        resp = await client.delete("/steering/bye.md")
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get("/steering/bye.md")
        assert get_resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_not_found(self, client):
        resp = await client.delete("/steering/nope.md")
        assert resp.status_code == 404
