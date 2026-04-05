"""
Unit tests for the settings router.

Tests GET / and PUT / endpoints for reading and updating settings.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.routers.settings import router


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeMetadataStore:
    """Minimal in-memory metadata store for testing (no SQLite)."""

    def __init__(self):
        self._prefs: dict = {}  # user_id -> settings dict

    def load_user_preferences(self, user_id: str):
        data = self._prefs.get(user_id)
        if data is None:
            return None
        from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

        return RetrievalConfig.from_json(json.dumps(data))

    def save_user_preferences(self, user_id: str, settings) -> None:
        if hasattr(settings, "to_json"):
            self._prefs[user_id] = json.loads(settings.to_json())
        else:
            self._prefs[user_id] = settings

    def load_raw_preferences(self, user_id: str):
        return self._prefs.get(user_id)

    def save_raw_preferences(self, user_id: str, data: dict) -> None:
        self._prefs[user_id] = data


@pytest.fixture
def fake_facade():
    facade = MagicMock()
    store = FakeMetadataStore()
    facade.metadata_store = store
    return facade


@pytest.fixture
def settings_app(fake_facade):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_kb_facade] = lambda: fake_facade
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(settings_app):
    transport = ASGITransport(app=settings_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestGetSettings:
    """GET /settings — return current settings."""

    @pytest.mark.anyio
    async def test_returns_defaults(self, client):
        resp = await client.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "top_k" in data
        assert "max_depth" in data
        assert "model" in data
        assert "temperature" in data
        assert "auto_review" in data

    @pytest.mark.anyio
    async def test_returns_correct_types(self, client):
        resp = await client.get("/settings")
        data = resp.json()
        assert isinstance(data["top_k"], int)
        assert isinstance(data["max_depth"], int)
        assert isinstance(data["model"], str)
        assert isinstance(data["temperature"], (int, float))
        assert isinstance(data["auto_review"], bool)


class TestUpdateSettings:
    """PUT /settings — update settings."""

    @pytest.mark.anyio
    async def test_update_top_k(self, client):
        resp = await client.put("/settings", json={"top_k": 42})
        assert resp.status_code == 200
        data = resp.json()
        assert data["top_k"] == 42

    @pytest.mark.anyio
    async def test_update_max_depth(self, client):
        resp = await client.put("/settings", json={"max_depth": 5})
        assert resp.status_code == 200
        assert resp.json()["max_depth"] == 5

    @pytest.mark.anyio
    async def test_update_model(self, client):
        resp = await client.put("/settings", json={"model": "gpt-4o"})
        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4o"

    @pytest.mark.anyio
    async def test_update_temperature(self, client):
        resp = await client.put("/settings", json={"temperature": 0.7})
        assert resp.status_code == 200
        assert resp.json()["temperature"] == 0.7

    @pytest.mark.anyio
    async def test_update_auto_review(self, client):
        resp = await client.put("/settings", json={"auto_review": False})
        assert resp.status_code == 200
        assert resp.json()["auto_review"] is False

    @pytest.mark.anyio
    async def test_update_multiple_fields(self, client):
        resp = await client.put(
            "/settings",
            json={"top_k": 10, "temperature": 1.5, "model": "claude-3"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["top_k"] == 10
        assert data["temperature"] == 1.5
        assert data["model"] == "claude-3"

    @pytest.mark.anyio
    async def test_partial_update_preserves_other_fields(self, client):
        await client.put("/settings", json={"top_k": 20, "model": "gpt-4o"})
        resp = await client.put("/settings", json={"temperature": 0.5})
        data = resp.json()
        assert data["top_k"] == 20
        assert data["model"] == "gpt-4o"
        assert data["temperature"] == 0.5

    @pytest.mark.anyio
    async def test_temperature_validation_too_high(self, client):
        resp = await client.put("/settings", json={"temperature": 3.0})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_temperature_validation_too_low(self, client):
        resp = await client.put("/settings", json={"temperature": -0.5})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_temperature_boundary_zero(self, client):
        resp = await client.put("/settings", json={"temperature": 0.0})
        assert resp.status_code == 200
        assert resp.json()["temperature"] == 0.0

    @pytest.mark.anyio
    async def test_temperature_boundary_two(self, client):
        resp = await client.put("/settings", json={"temperature": 2.0})
        assert resp.status_code == 200
        assert resp.json()["temperature"] == 2.0

    @pytest.mark.anyio
    async def test_empty_update_returns_current(self, client):
        resp = await client.put("/settings", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "top_k" in data
        assert "model" in data
