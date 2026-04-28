"""Read-only GitHub REST client for the audit pipeline.

Two primitives:
- `get_pr_files` lists files changed in a PR (filename + status + patch metadata).
- `get_file_content` returns text for a single file at a specific git ref.

Both accept an optional `httpx.Client` for test injection (`MockTransport`); the
default path opens a short-lived client per call. Auth is via PAT for M1 — the
same `Authorization: Bearer ...` shape M2 GitHub-App JWT will use.
"""

import base64
from typing import Any

import httpx

_GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(
    url: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> httpx.Response:
    if client is None:
        with httpx.Client() as owned:
            response = owned.get(url, headers=_headers(token), params=params, timeout=30)
    else:
        response = client.get(url, headers=_headers(token), params=params, timeout=30)
    response.raise_for_status()
    return response


def get_pr_files(
    *,
    repo_full_name: str,
    pr_number: int,
    token: str,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return GitHub's raw "files changed" array for a PR.

    Each entry carries `filename`, `status` (`added` / `modified` / `removed` / `renamed`),
    `patch`, `raw_url`, and others. The pipeline filters to `.py` files in `added`/`modified`
    state before fetching content.
    """
    url = f"{_GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/files"
    return _get(url, token=token, client=client).json()


def get_file_content(
    *,
    repo_full_name: str,
    path: str,
    ref: str,
    token: str,
    client: httpx.Client | None = None,
) -> str:
    """Return the UTF-8 text of a file at a specific git ref (SHA, branch, or tag).

    Uses the contents API which returns base64-encoded content for files under 1 MB.
    Larger files would need the blob API — out of scope for M1 since Python source
    files are virtually always small.
    """
    url = f"{_GITHUB_API}/repos/{repo_full_name}/contents/{path}"
    response = _get(url, token=token, params={"ref": ref}, client=client)
    data = response.json()
    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8")
    return data.get("content", "")
