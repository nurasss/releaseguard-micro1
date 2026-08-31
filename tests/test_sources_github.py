# path: tests/test_sources_github.py
"""Regression tests for the live GitHub adapter.

Every case here corresponds to a defect that survived into a tagged build
because the evaluation harness only ever exercised the fixture source. They
pin the three behaviours a live audit depends on: the repository endpoint is
addressed without a trailing slash, a copied token is normalised, and an API
failure is never reported as an empty repository.
"""

import httpx
import pytest

from app.sources.errors import GitHubAPIError
from app.sources.github import GitHubSource

REPO_URL = "https://github.com/octocat/Hello-World"
SHA = "1234567890123456789012345678901234567890"


def _source(handler, token: str | None = None) -> GitHubSource:
    return GitHubSource(
        repo_url=REPO_URL,
        token=token,
        transport=httpx.MockTransport(handler),
    )


def test_repository_endpoint_has_no_trailing_slash() -> None:
    """GitHub answers /repos/o/r with 200 and /repos/o/r/ with 404.

    An empty endpoint must therefore not append a separator, otherwise every
    live audit fails on its very first request.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        if request.url.path.startswith("/repos/octocat/Hello-World/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    metadata = _source(handler).get_repository_metadata()

    assert seen[0] == "/repos/octocat/Hello-World"
    assert not seen[0].endswith("/")
    assert metadata["default_branch"] == "main"


@pytest.mark.parametrize("raw_token", ["  ghp_padded  ", "\tghp_padded\n"])
def test_surrounding_whitespace_is_stripped_from_token(raw_token: str) -> None:
    """A token pasted into .env keeps its padding and yields a malformed header."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"default_branch": "main", "private": True})

    _source(handler, token=raw_token).get_repository_metadata()

    assert seen == ["Bearer ghp_padded"]


def test_blank_token_sends_no_authorization_header() -> None:
    """A public repository must stay readable when the token is empty."""
    seen: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append("Authorization" in request.headers)
        return httpx.Response(200, json={"default_branch": "main", "private": True})

    _source(handler, token="   ").get_repository_metadata()

    assert seen == [False]


def test_tree_api_failure_raises_instead_of_reporting_an_empty_repository() -> None:
    """A rate limit must not become the claim that no files exist.

    Returning [] here previously produced a Verifier-confirmed critical finding
    that no CI workflow existed, which SPEC section 24 and NFR-10 forbid.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": SHA}})
        if "/git/trees/" in request.url.path:
            return httpx.Response(403, json={"message": "API rate limit exceeded"})
        return httpx.Response(200, json={})

    source = _source(handler)
    source.resolve_ref("main")

    with pytest.raises(GitHubAPIError) as excinfo:
        source.get_tree()

    assert "403" in str(excinfo.value)


def test_workflow_files_do_not_silently_disappear_on_api_failure() -> None:
    """The workflow listing is derived from the tree and inherits its failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": SHA}})
        if "/git/trees/" in request.url.path:
            return httpx.Response(500, json={})
        return httpx.Response(200, json={})

    source = _source(handler)
    source.resolve_ref("main")

    with pytest.raises(GitHubAPIError):
        source.get_workflow_files()


def test_actions_runs_failure_raises_instead_of_reporting_no_runs() -> None:
    """An unavailable Actions API is not evidence that CI never ran."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": SHA}})
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(403, json={"message": "API rate limit exceeded"})
        return httpx.Response(200, json={})

    source = _source(handler)
    source.resolve_ref("main")

    with pytest.raises(GitHubAPIError):
        source.get_workflow_runs()


def test_tag_listing_failure_raises_instead_of_reporting_no_tags() -> None:
    """A 403 on /tags is not evidence that the repository has no releases."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        if request.url.path.endswith("/tags"):
            return httpx.Response(403, json={"message": "API rate limit exceeded"})
        return httpx.Response(200, json=[])

    with pytest.raises(GitHubAPIError) as excinfo:
        _source(handler).get_repository_metadata()

    assert "tags" in str(excinfo.value)


def test_empty_repository_still_yields_an_empty_tree() -> None:
    """A genuinely empty repository answers 200 and must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": SHA}})
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, json={"tree": []})
        return httpx.Response(200, json={})

    source = _source(handler)
    source.resolve_ref("main")

    assert source.get_tree() == []
