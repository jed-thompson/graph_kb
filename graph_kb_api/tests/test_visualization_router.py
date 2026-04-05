"""
Unit tests for the visualization router.

Tests the GET /repos/{repo_id}/{viz_type} endpoint using a mocked
facade and visualization service.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.graph_kb.models.enums import GraphEdgeType, GraphNodeType
from graph_kb_api.graph_kb.models.visualization import (
    VisEdge,
    VisGraph,
    VisNode,
    VisualizationResult,
)
from graph_kb_api.routers.visualization import router

_test_app = FastAPI()
_test_app.include_router(router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vis_service(result=None, graph=None):
    """Create a mock visualization service."""
    svc = MagicMock()
    svc.generate_visualization.return_value = result or VisualizationResult(
        success=True, html="<html></html>", node_count=0, edge_count=0
    )
    svc._query_graph.return_value = graph or VisGraph()
    return svc


def _make_facade(vis_service=None):
    facade = MagicMock()
    facade.visualization_service = vis_service
    return facade


def _sample_graph():
    """Return a small VisGraph with two nodes and one edge."""
    nodes = [
        VisNode(
            id="n1",
            label="main.py",
            node_type=GraphNodeType.FILE,
            full_path="src/main.py",
        ),
        VisNode(
            id="n2",
            label="utils.py",
            node_type=GraphNodeType.FILE,
            full_path="src/utils.py",
        ),
    ]
    edges = [
        VisEdge(source="n1", target="n2", edge_type=GraphEdgeType.IMPORTS),
    ]
    return VisGraph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_vis_service():
    graph = _sample_graph()
    result = VisualizationResult(
        success=True,
        html="<html>viz</html>",
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )
    return _make_vis_service(result=result, graph=graph)


@pytest.fixture
def mock_facade(mock_vis_service):
    return _make_facade(vis_service=mock_vis_service)


@pytest.fixture
async def client(mock_facade):
    _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
    transport = ASGITransport(app=_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    _test_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetVisualization:
    """GET /api/v1/visualize/repos/{repo_id}/{viz_type}"""

    @pytest.mark.anyio
    async def test_success_returns_nodes_and_edges(self, client):
        resp = await client.get("/api/v1/visualize/repos/my-repo/architecture")
        assert resp.status_code == 200
        data = resp.json()
        assert data["viz_type"] == "architecture"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["html"] == "<html>viz</html>"

    @pytest.mark.anyio
    async def test_node_fields(self, client):
        resp = await client.get("/api/v1/visualize/repos/my-repo/dependencies")
        data = resp.json()
        node = data["nodes"][0]
        assert "id" in node
        assert "label" in node
        assert "type" in node

    @pytest.mark.anyio
    async def test_edge_references_valid_node_ids(self, client):
        resp = await client.get("/api/v1/visualize/repos/my-repo/calls")
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids

    @pytest.mark.anyio
    async def test_invalid_viz_type_returns_422(self, client):
        resp = await client.get("/api/v1/visualize/repos/my-repo/invalid_type")
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_repo_not_found_returns_404(self, mock_facade):
        svc = mock_facade.visualization_service
        svc.generate_visualization.return_value = VisualizationResult(
            success=False, error="Repository 'bad-repo' not found"
        )
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/visualize/repos/bad-repo/architecture")
        _test_app.dependency_overrides.clear()
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_repo_not_indexed_returns_404(self, mock_facade):
        svc = mock_facade.visualization_service
        svc.generate_visualization.return_value = VisualizationResult(
            success=False, error="Repository 'x' is not indexed"
        )
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/visualize/repos/x/full")
        _test_app.dependency_overrides.clear()
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_service_unavailable_returns_503(self):
        facade = _make_facade(vis_service=None)
        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/visualize/repos/repo/architecture")
        _test_app.dependency_overrides.clear()
        assert resp.status_code == 503

    @pytest.mark.anyio
    async def test_all_viz_types_accepted(self, client, mock_vis_service):
        for vt in [
            "architecture",
            "calls",
            "dependencies",
            "full",
            "comprehensive",
            "call_chain",
            "hotspots",
        ]:
            resp = await client.get(f"/api/v1/visualize/repos/repo/{vt}")
            assert resp.status_code == 200, f"Failed for viz_type={vt}"

    @pytest.mark.anyio
    async def test_edges_with_invalid_refs_are_filtered(self, mock_facade):
        """Edges referencing non-existent node IDs should be excluded."""
        graph = _sample_graph()
        # Add a dangling edge
        graph.edges.append(
            VisEdge(
                source="n1",
                target="ghost",
                edge_type=GraphEdgeType.IMPORTS,
            )
        )
        svc = mock_facade.visualization_service
        svc._query_graph.return_value = graph
        svc.generate_visualization.return_value = VisualizationResult(
            success=True, html="<html></html>", node_count=2, edge_count=2
        )

        _test_app.dependency_overrides[get_graph_kb_facade] = lambda: mock_facade
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/visualize/repos/repo/architecture")
        _test_app.dependency_overrides.clear()

        data = resp.json()
        # Only the valid edge (n1 -> n2) should be present
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source"] == "n1"
        assert data["edges"][0]["target"] == "n2"
