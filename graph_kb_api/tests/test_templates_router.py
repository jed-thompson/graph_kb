"""
Unit tests for the template management router.

Tests both endpoints: POST /upload and GET /.
"""

import shutil
import tempfile
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.graph_kb.prompts.prompt_manager import GraphKBPromptManager
from graph_kb_api.routers.templates import router


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_templates_dir():
    """Create a temporary directory for prompt templates."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_facade(tmp_templates_dir):
    """Create a mock facade with a real prompt manager backed by a temp dir."""
    facade = MagicMock()
    facade.prompt_manager = GraphKBPromptManager(templates_dir=tmp_templates_dir)
    return facade


@pytest.fixture
def templates_app(mock_facade):
    """Create a test FastAPI app with the templates router."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(templates_app):
    transport = ASGITransport(app=templates_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestListTemplates:
    """GET /templates — list all available templates."""

    @pytest.mark.anyio
    async def test_empty_list(self, client):
        resp = await client.get("/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["templates"] == []

    @pytest.mark.anyio
    async def test_list_after_upload(self, client):
        await client.post(
            "/templates/upload",
            files={
                "file": (
                    "my_template.md",
                    b"# My Template\nGenerate a spec.",
                    "text/markdown",
                )
            },
        )
        resp = await client.get("/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["templates"]) == 1
        assert data["templates"][0]["name"] == "My Template"
        assert "Generate a spec." in data["templates"][0]["description"]


class TestUploadTemplate:
    """POST /templates/upload — upload a new template."""

    @pytest.mark.anyio
    async def test_upload_returns_metadata(self, client):
        resp = await client.post(
            "/templates/upload",
            files={
                "file": (
                    "api_spec.md",
                    b"# API Spec\nCreate an API specification.",
                    "text/markdown",
                )
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Api Spec"
        assert "Create an API specification." in data["description"]

    @pytest.mark.anyio
    async def test_upload_adds_md_extension(self, client):
        resp = await client.post(
            "/templates/upload",
            files={
                "file": ("readme", b"# Readme\nProject readme template.", "text/plain")
            },
        )
        assert resp.status_code == 200
        # After upload, the template should appear in the list
        list_resp = await client.get("/templates")
        names = [t["name"] for t in list_resp.json()["templates"]]
        assert "Readme" in names

    @pytest.mark.anyio
    async def test_uploaded_template_available_in_list(self, client):
        """After upload, the template should be available as a generation command."""
        await client.post(
            "/templates/upload",
            files={
                "file": (
                    "design_doc.md",
                    b"# Design Doc\nGenerate a design document.",
                    "text/markdown",
                )
            },
        )
        await client.post(
            "/templates/upload",
            files={
                "file": (
                    "test_plan.md",
                    b"# Test Plan\nGenerate a test plan.",
                    "text/markdown",
                )
            },
        )
        resp = await client.get("/templates")
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert len(templates) == 2
        names = {t["name"] for t in templates}
        assert "Design Doc" in names
        assert "Test Plan" in names

    @pytest.mark.anyio
    async def test_upload_with_no_description_line(self, client):
        """Template with only a heading gets a fallback description."""
        resp = await client.post(
            "/templates/upload",
            files={"file": ("bare.md", b"# Bare Template\n\n", "text/markdown")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Prompt template"


class TestPromptManagerUnavailable:
    """Endpoints return 503 when prompt manager is None."""

    @pytest.mark.anyio
    async def test_upload_503(self):
        facade = MagicMock()
        facade.prompt_manager = None

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_graph_kb_facade] = lambda: facade

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/templates/upload",
                files={"file": ("t.md", b"content", "text/markdown")},
            )
            assert resp.status_code == 503

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_list_503(self):
        facade = MagicMock()
        facade.prompt_manager = None

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_graph_kb_facade] = lambda: facade

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/templates")
            assert resp.status_code == 503

        app.dependency_overrides.clear()
