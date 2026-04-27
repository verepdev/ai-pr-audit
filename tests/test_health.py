"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient

from ai_pr_audit.app import app

client = TestClient(app)


def test_health_returns_200_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
