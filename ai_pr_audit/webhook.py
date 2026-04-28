"""GitHub webhook receiver — verifies HMAC and dispatches PR events to the audit pipeline."""

import hmac
import json
import os
from hashlib import sha256

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ai_pr_audit.pipeline import audit_pr

router = APIRouter()


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature in constant time."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _should_audit(event: str | None, action: str | None) -> bool:
    return event == "pull_request" and action in ("opened", "synchronize")


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> dict[str, str]:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="webhook secret not configured")

    payload = await request.body()
    if not verify_signature(payload, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    queued = False
    if x_github_event == "pull_request":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {"received": x_github_event, "queued": "false"}

        if _should_audit(x_github_event, data.get("action")):
            token = os.getenv("GITHUB_TOKEN")
            if token:
                background_tasks.add_task(
                    audit_pr,
                    repo_full_name=data["repository"]["full_name"],
                    pr_number=data["pull_request"]["number"],
                    head_sha=data["pull_request"]["head"]["sha"],
                    token=token,
                )
                queued = True

    return {"received": x_github_event or "unknown", "queued": "true" if queued else "false"}
