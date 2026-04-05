"""Tests for the plan sessions REST router."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_db_session
from graph_kb_api.routers.plan import router

_test_app = FastAPI()
_test_app.include_router(router, prefix="/api/v1")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async def _fake_db():
        yield object()

    _test_app.dependency_overrides[get_db_session] = _fake_db
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _test_app.dependency_overrides.clear()


class TestPlanArtifactListRoute:
    @pytest.mark.asyncio
    async def test_list_plan_artifacts_returns_sorted_manifest_entries(self, client: AsyncClient):
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=SimpleNamespace(id="session-1"))

        mock_backend = MagicMock()
        mock_backend.list_directory = AsyncMock(
            return_value=[
                "specs/session-1/context/document_section_index.json",
                "specs/session-1/output/final_spec.md",
            ]
        )
        mock_backend.retrieve = AsyncMock(
            side_effect=[
                SimpleNamespace(
                    size_bytes=1400,
                    created_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                    content_type="application/json",
                ),
                SimpleNamespace(
                    size_bytes=2800,
                    created_at=datetime(2026, 4, 2, 8, 30, tzinfo=UTC),
                    content_type="text/markdown",
                ),
            ]
        )
        mock_storage = SimpleNamespace(backend=mock_backend)

        with (
            patch("graph_kb_api.routers.plan.PlanSessionRepository", return_value=mock_repo),
            patch("graph_kb_api.routers.plan.BlobStorage.from_env", return_value=mock_storage),
        ):
            response = await client.get("/api/v1/plan/sessions/session-1/artifacts")

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["artifacts"] == [
            {
                "key": "output/final_spec.md",
                "summary": "Final spec",
                "size_bytes": 2800,
                "created_at": "2026-04-02T08:30:00+00:00",
                "content_type": "text/markdown",
            },
            {
                "key": "context/document_section_index.json",
                "summary": "Document section index",
                "size_bytes": 1400,
                "created_at": "2026-04-01T12:00:00+00:00",
                "content_type": "application/json",
            },
        ]

    @pytest.mark.asyncio
    async def test_list_plan_artifacts_returns_404_for_missing_session(self, client: AsyncClient):
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch("graph_kb_api.routers.plan.PlanSessionRepository", return_value=mock_repo):
            response = await client.get("/api/v1/plan/sessions/missing-session/artifacts")

        assert response.status_code == 404
        assert response.json()["detail"] == "Plan session not found"
