"""GitHub webhook receiver — verifies HMAC signature and accepts pull_request events."""

import hmac
import os
from hashlib import sha256

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify a GitHub webhook HMAC-SHA256 signature in constant time."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> dict[str, str]:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="webhook secret not configured")

    payload = await request.body()
    if not verify_signature(payload, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    return {"received": x_github_event or "unknown"}
