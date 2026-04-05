"""
WebSocket endpoint tests.

Tests WebSocket connection and message handling.
"""

from starlette.testclient import TestClient

from graph_kb_api.main import app


class TestWebSocketEndpoints:
    """Test WebSocket endpoints."""

    def test_websocket_connection(self):
        """Test basic WebSocket connection."""
        client = TestClient(app)
        with client.websocket_connect("/ws") as websocket:
            # Send start message
            websocket.send_json({
                "type": "start",
                "payload": {
                    "workflow_type": "ask-code",
                    "query": "test query",
                    "repo_id": "test-repo"
                }
            })

            # Should receive acknowledgement
            data = websocket.receive_json()
            assert data["type"] == "progress"
            assert "workflow_id" in data

    def test_ask_code_websocket(self):
        """Test ask-code specific endpoint."""
        client = TestClient(app)
        with client.websocket_connect("/ws/ask-code") as websocket:
            websocket.send_json({
                "type": "start",
                "payload": {
                    "query": "How does authentication work?",
                    "repo_id": "test-repo"
                }
            })

            # Should receive at least one message
            data = websocket.receive_json()
            assert "type" in data

    def test_ingest_websocket(self):
        """Test ingest specific endpoint."""
        client = TestClient(app)
        with client.websocket_connect("/ws/ingest") as websocket:
            websocket.send_json({
                "type": "start",
                "payload": {
                    "git_url": "https://github.com/example/repo",
                    "branch": "main"
                }
            })

            # Should receive acknowledgement
            data = websocket.receive_json()
            assert "type" in data
