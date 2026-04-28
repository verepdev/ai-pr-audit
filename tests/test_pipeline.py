"""End-to-end tests for the audit pipeline."""

import base64
import json

import httpx

from ai_pr_audit.pipeline import audit_pr


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _make_client(routes: dict[str, tuple[int, object]]) -> tuple[httpx.Client, list]:
    """Build a Client whose transport routes requests by URL substring.

    `routes`: maps URL substring → (status, json body). The first matching pattern
    wins; unmocked URLs return 404 and are visible in the captured requests log.
    """
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        url = str(request.url)
        for pattern, (status, body) in routes.items():
            if pattern in url:
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": f"unmocked: {url}"})

    return httpx.Client(transport=httpx.MockTransport(handler)), log


class TestNoPythonFiles:
    def test_skips_when_pr_has_no_py_files(self) -> None:
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "README.md", "status": "modified"}],
                ),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        assert result == {
            "files_analyzed": 0,
            "hallucinations_found": 0,
            "review_posted": False,
        }
        # Only the file-list call happened
        assert len(log) == 1

    def test_skips_removed_py_file(self) -> None:
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "src/x.py", "status": "removed"}],
                ),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        assert result["files_analyzed"] == 0
        assert len(log) == 1


class TestCleanPR:
    def test_no_review_when_no_hallucinations(self) -> None:
        clean_source = "import os\nfrom fastapi import FastAPI\n"
        manifest = '[project]\nname = "demo"\ndependencies = ["fastapi"]\n'
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "src/x.py", "status": "modified"}],
                ),
                "/contents/pyproject.toml": (
                    200,
                    {"content": _b64(manifest), "encoding": "base64"},
                ),
                "/contents/src/x.py": (
                    200,
                    {"content": _b64(clean_source), "encoding": "base64"},
                ),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        assert result == {
            "files_analyzed": 1,
            "hallucinations_found": 0,
            "review_posted": False,
        }
        assert not any("/reviews" in str(r.url) for r in log)


class TestHallucinationFound:
    def test_posts_review_with_inline_comments(self) -> None:
        bad_source = "import nonexistent_pkg\nimport polars as pd\n"
        manifest = '[project]\nname = "demo"\ndependencies = ["fastapi"]\n'
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "src/x.py", "status": "added"}],
                ),
                "/contents/pyproject.toml": (
                    200,
                    {"content": _b64(manifest), "encoding": "base64"},
                ),
                "/contents/src/x.py": (
                    200,
                    {"content": _b64(bad_source), "encoding": "base64"},
                ),
                "/pulls/1/reviews": (200, {"id": 999, "state": "COMMENTED"}),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        assert result == {
            "files_analyzed": 1,
            "hallucinations_found": 2,
            "review_posted": True,
        }

        review_req = next(r for r in log if "/reviews" in str(r.url))
        body = json.loads(review_req.content)
        assert body["event"] == "COMMENT"
        assert len(body["comments"]) == 2
        joined = " ".join(c["body"] for c in body["comments"])
        assert "nonexistent_pkg" in joined
        assert "polars" in joined
        assert "ai-pr-audit found 2" in body["body"]

    def test_per_line_comment_carries_correct_path_and_line(self) -> None:
        bad_source = "import os\nimport bogus_lib\n"  # line 2
        manifest = '[project]\nname = "demo"\n'
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "deep/path/foo.py", "status": "modified"}],
                ),
                "/contents/pyproject.toml": (
                    200,
                    {"content": _b64(manifest), "encoding": "base64"},
                ),
                "/contents/deep/path/foo.py": (
                    200,
                    {"content": _b64(bad_source), "encoding": "base64"},
                ),
                "/pulls/1/reviews": (200, {"id": 1}),
            }
        )
        audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        review_req = next(r for r in log if "/reviews" in str(r.url))
        comment = json.loads(review_req.content)["comments"][0]
        assert comment["path"] == "deep/path/foo.py"
        assert comment["line"] == 2


class TestManifestFallback:
    def test_missing_pyproject_means_empty_manifest_so_everything_flagged(self) -> None:
        # Without a manifest, even legit deps get flagged (still skips stdlib).
        source = "import os\nimport fastapi\n"  # os ok, fastapi flagged
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "x.py", "status": "added"}],
                ),
                "/contents/pyproject.toml": (404, {"message": "Not Found"}),
                "/contents/x.py": (
                    200,
                    {"content": _b64(source), "encoding": "base64"},
                ),
                "/pulls/1/reviews": (200, {"id": 1}),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        assert result["hallucinations_found"] == 1  # fastapi only
        review = next(r for r in log if "/reviews" in str(r.url))
        body = json.loads(review.content)
        assert "fastapi" in body["comments"][0]["body"]


class TestErrorTolerance:
    def test_skips_file_with_syntax_error(self) -> None:
        bad_python = "def broken(:\n"  # SyntaxError
        manifest = '[project]\nname = "demo"\n'
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [{"filename": "x.py", "status": "added"}],
                ),
                "/contents/pyproject.toml": (
                    200,
                    {"content": _b64(manifest), "encoding": "base64"},
                ),
                "/contents/x.py": (
                    200,
                    {"content": _b64(bad_python), "encoding": "base64"},
                ),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        # Pipeline didn't crash; just no findings since file couldn't parse
        assert result["hallucinations_found"] == 0
        assert result["review_posted"] is False

    def test_skips_file_when_content_fetch_fails(self) -> None:
        manifest = '[project]\nname = "demo"\n'
        client, log = _make_client(
            {
                "/pulls/1/files": (
                    200,
                    [
                        {"filename": "ok.py", "status": "added"},
                        {"filename": "missing.py", "status": "added"},
                    ],
                ),
                "/contents/pyproject.toml": (
                    200,
                    {"content": _b64(manifest), "encoding": "base64"},
                ),
                "/contents/ok.py": (
                    200,
                    {"content": _b64("import os\n"), "encoding": "base64"},
                ),
                "/contents/missing.py": (404, {"message": "Not Found"}),
            }
        )
        result = audit_pr(
            repo_full_name="o/r",
            pr_number=1,
            head_sha="abc",
            token="t",
            client=client,
        )
        # ok.py analyzed fine (no flags), missing.py skipped, no review
        assert result["files_analyzed"] == 2
        assert result["hallucinations_found"] == 0
