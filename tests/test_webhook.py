"""Tests for webhook signature verification and the /webhook endpoint."""

import hmac
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from ai_pr_audit.app import app
from ai_pr_audit.webhook import verify_signature


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, sha256).hexdigest()


def test_verify_signature_valid() -> None:
    secret = "test-secret"
    payload = b'{"action":"opened"}'
    assert verify_signature(payload, _sign(payload, secret), secret) is True


def test_verify_signature_missing_header() -> None:
    assert verify_signature(b"any", None, "secret") is False


def test_verify_signature_wrong_prefix() -> None:
    assert verify_signature(b"any", "sha1=abcd", "secret") is False


def test_verify_signature_wrong_digest() -> None:
    assert verify_signature(b"any", "sha256=" + "0" * 64, "secret") is False


def test_verify_signature_wrong_secret() -> None:
    payload = b'{"action":"opened"}'
    sig = _sign(payload, "wrong-secret")
    assert verify_signature(payload, sig, "right-secret") is False


def test_webhook_rejects_missing_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    client = TestClient(app)
    response = client.post("/webhook", json={"action": "opened"})
    assert response.status_code == 401


def test_webhook_accepts_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    payload = b'{"action":"opened"}'
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"received": "pull_request"}


def test_webhook_500_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    client = TestClient(app)
    response = client.post("/webhook", json={"action": "opened"})
    assert response.status_code == 500
