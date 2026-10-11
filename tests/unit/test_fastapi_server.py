"""Tests for ALP FastAPI Core server including WebSockets."""
import os
import sys
import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
for sub in ("policy-engine", "capability-engine", "verification-engine",
            "compatibility", "vendor-adapters", "desktop"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from backend.fastapi_core.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "UP"


def test_docs_and_openapi(client):
    r = client.get("/docs")
    assert r.status_code == 200
    r_json = client.get("/openapi.json")
    assert r_json.status_code == 200
    assert "paths" in r_json.json()


def test_bootstrap_endpoint(client):
    r = client.get("/api/v1/bootstrap")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "needs_bootstrap" in data["data"]


def test_auth_protection(client):
    r = client.get("/api/v1/devices")
    assert r.status_code == 401
    data = r.json()
    assert data["ok"] is False


def test_root_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ManageEngine Mobile Device Manager Plus" in r.text


def test_websocket_connection(client):
    with client.websocket_connect("/ws") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert "pong" in data
