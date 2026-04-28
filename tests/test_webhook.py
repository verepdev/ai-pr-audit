"""Tests for webhook signature verification and the /webhook endpoint."""

import hmac
import json
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
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = TestClient(app)
    response = client.post("/webhook", json={"action": "opened"})
    assert response.status_code == 401


def test_webhook_accepts_valid_signature_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
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
    assert response.json() == {"received": "pull_request", "queued": "false"}


def test_webhook_500_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    client = TestClient(app)
    response = client.post("/webhook", json={"action": "opened"})
    assert response.status_code == 500


def test_webhook_queues_pull_request_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    calls: list[dict] = []

    def fake_audit_pr(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", fake_audit_pr)

    payload_dict = {
        "action": "opened",
        "repository": {"full_name": "verepdev/demo"},
        "pull_request": {"number": 42, "head": {"sha": "deadbeef"}},
    }
    payload = json.dumps(payload_dict).encode()
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
    assert response.json() == {"received": "pull_request", "queued": "true"}
    assert len(calls) == 1
    assert calls[0]["repo_full_name"] == "verepdev/demo"
    assert calls[0]["pr_number"] == 42
    assert calls[0]["head_sha"] == "deadbeef"
    assert calls[0]["token"] == "ghp_test"


def test_webhook_queues_synchronize_action(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls: list[dict] = []
    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", lambda **kwargs: calls.append(kwargs))

    payload_dict = {
        "action": "synchronize",
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 1, "head": {"sha": "abc"}},
    }
    payload = json.dumps(payload_dict).encode()
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.json()["queued"] == "true"
    assert len(calls) == 1


def test_webhook_does_not_queue_closed_action(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls: list[dict] = []
    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", lambda **kwargs: calls.append(kwargs))

    payload_dict = {
        "action": "closed",
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 1, "head": {"sha": "abc"}},
    }
    payload = json.dumps(payload_dict).encode()
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.json()["queued"] == "false"
    assert calls == []


def test_webhook_does_not_queue_non_pr_event(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls: list[dict] = []
    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", lambda **kwargs: calls.append(kwargs))

    payload = b'{"zen":"keep it logically awesome"}'
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
        },
    )
    assert response.json() == {"received": "ping", "queued": "false"}
    assert calls == []


def test_webhook_does_not_queue_when_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls: list[dict] = []
    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", lambda **kwargs: calls.append(kwargs))

    payload_dict = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 1, "head": {"sha": "abc"}},
    }
    payload = json.dumps(payload_dict).encode()
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.json()["queued"] == "false"
    assert calls == []


def test_webhook_does_not_queue_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    calls: list[dict] = []
    monkeypatch.setattr("ai_pr_audit.webhook.audit_pr", lambda **kwargs: calls.append(kwargs))

    payload = b"not json"
    sig = _sign(payload, secret)

    client = TestClient(app)
    response = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.json()["queued"] == "false"
    assert calls == []
