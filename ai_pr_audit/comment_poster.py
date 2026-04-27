"""Posts a single GitHub PR review carrying every hallucination as an inline comment.

One review > many top-level comments — keeps the PR conversation tidy and lets the
dev see all findings in one collapsible block. Authentication is via PAT for M1
(static token); GitHub App JWT lands in M2 when we apply for the Marketplace.
"""

from dataclasses import dataclass
from typing import Any

import httpx

_GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class PRComment:
    """A single inline comment on a specific line of a specific file in a PR diff."""

    path: str
    line: int
    body: str


def post_review(
    *,
    repo_full_name: str,
    pr_number: int,
    comments: list[PRComment],
    token: str,
    summary: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Post a PR review with `comments` as inline annotations.

    Returns the parsed JSON response (review object) on success. Empty `comments`
    is a no-op and returns `{}`. Raises `httpx.HTTPStatusError` on non-2xx — the
    caller decides whether to retry or surface to the user.

    Pass `client` to inject a pre-configured `httpx.Client` (used in tests with
    `MockTransport`). Otherwise a short-lived client is created per call.
    """
    if not comments:
        return {}

    payload: dict[str, Any] = {
        "event": "COMMENT",
        "comments": [
            {"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in comments
        ],
    }
    if summary:
        payload["body"] = summary

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{_GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

    if client is None:
        with httpx.Client() as owned:
            response = owned.post(url, json=payload, headers=headers, timeout=30)
    else:
        response = client.post(url, json=payload, headers=headers, timeout=30)

    response.raise_for_status()
    return response.json()
