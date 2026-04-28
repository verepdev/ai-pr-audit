"""End-to-end audit pipeline: webhook payload → posted review.

Walks a single PR's changed Python files, runs the hallucination detector against
the project's `pyproject.toml` manifest, and posts every finding back to GitHub
as inline review comments. Single entry point (`audit_pr`) so the webhook handler
can hand off and return 200 immediately.
"""

from typing import Any

import httpx

from ai_pr_audit.ast_imports import extract_imports
from ai_pr_audit.comment_poster import PRComment, post_review
from ai_pr_audit.dep_manifest import DepManifest, parse_pyproject_toml
from ai_pr_audit.detector import Hallucination, detect_hallucinations
from ai_pr_audit.github_client import get_file_content, get_pr_files


def _empty_manifest() -> DepManifest:
    return DepManifest(project_name=None, declared=frozenset())


def _fetch_manifest(
    *,
    repo_full_name: str,
    ref: str,
    token: str,
    client: httpx.Client | None = None,
) -> DepManifest:
    """Read `pyproject.toml` at `ref`. Missing file → empty manifest (everything flagged)."""
    try:
        content = get_file_content(
            repo_full_name=repo_full_name,
            path="pyproject.toml",
            ref=ref,
            token=token,
            client=client,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return _empty_manifest()
        raise
    return parse_pyproject_toml(content)


def _format_comment(filename: str, h: Hallucination) -> PRComment:
    return PRComment(
        path=filename,
        line=h.line,
        body=f"⚠️ **AI hallucination check** — {h.reason}",
    )


def audit_pr(
    *,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    token: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Run the full pipeline for one PR. Returns a small summary dict."""
    files = get_pr_files(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        token=token,
        client=client,
    )
    py_files = [
        f
        for f in files
        if f.get("filename", "").endswith(".py") and f.get("status") in ("added", "modified")
    ]
    if not py_files:
        return {"files_analyzed": 0, "hallucinations_found": 0, "review_posted": False}

    manifest = _fetch_manifest(
        repo_full_name=repo_full_name,
        ref=head_sha,
        token=token,
        client=client,
    )

    comments: list[PRComment] = []
    for f in py_files:
        filename = f["filename"]
        try:
            source = get_file_content(
                repo_full_name=repo_full_name,
                path=filename,
                ref=head_sha,
                token=token,
                client=client,
            )
        except httpx.HTTPStatusError:
            # File became unreachable between PR-files listing and content fetch
            # (rare race). Skip silently rather than failing the whole audit.
            continue
        try:
            imports = extract_imports(source)
        except SyntaxError:
            # PR contains a file with a syntax error — out of M1 scope to handle.
            continue
        for h in detect_hallucinations(imports, manifest):
            comments.append(_format_comment(filename, h))

    if comments:
        post_review(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            comments=comments,
            token=token,
            summary=(
                f"ai-pr-audit found {len(comments)} possible hallucinated "
                f"import{'s' if len(comments) != 1 else ''}."
            ),
            client=client,
        )

    return {
        "files_analyzed": len(py_files),
        "hallucinations_found": len(comments),
        "review_posted": bool(comments),
    }
