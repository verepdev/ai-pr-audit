"""Tests for the GitHub PR review comment poster."""

import json

import httpx
import pytest

from ai_pr_audit.comment_poster import PRComment, post_review


def _record(captured: dict, status: int = 200, body: dict | None = None) -> httpx.Client:
    """Build an httpx Client whose transport captures the outgoing request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content) if request.content else None
        return httpx.Response(status, json=body or {"id": 1, "state": "COMMENTED"})

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestNoOpForEmpty:
    def test_empty_comments_returns_empty_dict_no_request(self) -> None:
        captured: dict = {}
        client = _record(captured)
        result = post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[],
            token="t",
            client=client,
        )
        assert result == {}
        assert captured == {}


class TestPayloadShape:
    def test_url_is_pulls_reviews(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="verepdev/demo",
            pr_number=42,
            comments=[PRComment(path="src/x.py", line=10, body="bad")],
            token="t",
            client=_record(captured),
        )
        assert captured["url"] == "https://api.github.com/repos/verepdev/demo/pulls/42/reviews"

    def test_method_is_post(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=_record(captured),
        )
        assert captured["method"] == "POST"

    def test_event_is_comment(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=_record(captured),
        )
        assert captured["body"]["event"] == "COMMENT"

    def test_each_comment_carries_path_line_side_body(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="src/a.py", line=7, body="hello")],
            token="t",
            client=_record(captured),
        )
        comment = captured["body"]["comments"][0]
        assert comment == {
            "path": "src/a.py",
            "line": 7,
            "side": "RIGHT",
            "body": "hello",
        }

    def test_multiple_comments_all_in_one_request(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[
                PRComment(path="a.py", line=1, body="one"),
                PRComment(path="b.py", line=2, body="two"),
                PRComment(path="c.py", line=3, body="three"),
            ],
            token="t",
            client=_record(captured),
        )
        assert len(captured["body"]["comments"]) == 3

    def test_summary_added_as_body_field(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            summary="Found 1 hallucination.",
            client=_record(captured),
        )
        assert captured["body"]["body"] == "Found 1 hallucination."

    def test_no_summary_means_no_body_field(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=_record(captured),
        )
        assert "body" not in captured["body"]


class TestAuthHeaders:
    def test_authorization_bearer_token(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="ghp_secret",
            client=_record(captured),
        )
        assert captured["headers"]["authorization"] == "Bearer ghp_secret"

    def test_accept_github_json(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=_record(captured),
        )
        assert captured["headers"]["accept"] == "application/vnd.github+json"

    def test_pinned_api_version(self) -> None:
        captured: dict = {}
        post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=_record(captured),
        )
        assert captured["headers"]["x-github-api-version"] == "2022-11-28"


class TestResponseHandling:
    def test_returns_parsed_json_on_success(self) -> None:
        client = _record({}, status=200, body={"id": 999, "state": "COMMENTED"})
        result = post_review(
            repo_full_name="o/r",
            pr_number=1,
            comments=[PRComment(path="x.py", line=1, body="x")],
            token="t",
            client=client,
        )
        assert result == {"id": 999, "state": "COMMENTED"}

    def test_raises_on_non_2xx(self) -> None:
        client = _record({}, status=422, body={"message": "validation failed"})
        with pytest.raises(httpx.HTTPStatusError):
            post_review(
                repo_full_name="o/r",
                pr_number=1,
                comments=[PRComment(path="x.py", line=1, body="x")],
                token="t",
                client=client,
            )
