"""Tests for the GitHub REST client."""

import base64

import httpx
import pytest

from ai_pr_audit.github_client import get_file_content, get_pr_files


def _client(captured: dict, status: int = 200, body: object | None = None) -> httpx.Client:
    """Build an httpx Client whose transport captures the request and returns `body`."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["params"] = dict(request.url.params)
        return httpx.Response(status, json=body if body is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestGetPrFiles:
    def test_url_targets_pr_files_endpoint(self) -> None:
        captured: dict = {}
        client = _client(captured, body=[])
        get_pr_files(
            repo_full_name="verepdev/demo",
            pr_number=42,
            token="t",
            client=client,
        )
        assert captured["url"] == "https://api.github.com/repos/verepdev/demo/pulls/42/files"

    def test_method_is_get(self) -> None:
        captured: dict = {}
        get_pr_files(
            repo_full_name="o/r",
            pr_number=1,
            token="t",
            client=_client(captured, body=[]),
        )
        assert captured["method"] == "GET"

    def test_returns_parsed_list(self) -> None:
        files = [
            {"filename": "src/a.py", "status": "modified"},
            {"filename": "src/b.py", "status": "added"},
        ]
        client = _client({}, body=files)
        result = get_pr_files(
            repo_full_name="o/r",
            pr_number=1,
            token="t",
            client=client,
        )
        assert result == files

    def test_auth_headers_pinned(self) -> None:
        captured: dict = {}
        get_pr_files(
            repo_full_name="o/r",
            pr_number=1,
            token="ghp_abc",
            client=_client(captured, body=[]),
        )
        assert captured["headers"]["authorization"] == "Bearer ghp_abc"
        assert captured["headers"]["accept"] == "application/vnd.github+json"
        assert captured["headers"]["x-github-api-version"] == "2022-11-28"

    def test_raises_on_non_2xx(self) -> None:
        client = _client({}, status=404, body={"message": "Not Found"})
        with pytest.raises(httpx.HTTPStatusError):
            get_pr_files(
                repo_full_name="o/r",
                pr_number=1,
                token="t",
                client=client,
            )


class TestGetFileContent:
    def test_url_targets_contents_endpoint(self) -> None:
        captured: dict = {}
        body = {
            "content": base64.b64encode(b"print('ok')\n").decode(),
            "encoding": "base64",
        }
        get_file_content(
            repo_full_name="verepdev/demo",
            path="src/foo.py",
            ref="abc123",
            token="t",
            client=_client(captured, body=body),
        )
        # httpx normalises path; just check the path portion
        assert "/repos/verepdev/demo/contents/src/foo.py" in captured["url"]

    def test_ref_is_passed_as_query_param(self) -> None:
        captured: dict = {}
        body = {"content": base64.b64encode(b"x").decode(), "encoding": "base64"}
        get_file_content(
            repo_full_name="o/r",
            path="x.py",
            ref="deadbeef",
            token="t",
            client=_client(captured, body=body),
        )
        assert captured["params"]["ref"] == "deadbeef"

    def test_decodes_base64_to_utf8(self) -> None:
        source = "import os\nimport requests\n"
        body = {
            "content": base64.b64encode(source.encode()).decode(),
            "encoding": "base64",
        }
        result = get_file_content(
            repo_full_name="o/r",
            path="x.py",
            ref="main",
            token="t",
            client=_client({}, body=body),
        )
        assert result == source

    def test_handles_unencoded_content_passthrough(self) -> None:
        # Defensive: if GitHub ever returns plain content, don't crash
        body = {"content": "raw content", "encoding": "utf-8"}
        result = get_file_content(
            repo_full_name="o/r",
            path="x.py",
            ref="main",
            token="t",
            client=_client({}, body=body),
        )
        assert result == "raw content"

    def test_handles_unicode_source(self) -> None:
        source = "# türkçe yorum\nx = 'müzik'\n"
        body = {
            "content": base64.b64encode(source.encode("utf-8")).decode(),
            "encoding": "base64",
        }
        result = get_file_content(
            repo_full_name="o/r",
            path="x.py",
            ref="main",
            token="t",
            client=_client({}, body=body),
        )
        assert result == source

    def test_raises_on_404(self) -> None:
        client = _client({}, status=404, body={"message": "Not Found"})
        with pytest.raises(httpx.HTTPStatusError):
            get_file_content(
                repo_full_name="o/r",
                path="missing.py",
                ref="main",
                token="t",
                client=client,
            )
