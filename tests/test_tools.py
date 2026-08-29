# path: tests/test_tools.py
import inspect
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.evidence.store import EvidenceStore
from app.llm.types import ToolCall
from app.sources.base import MAX_GITHUB_SEARCH_FILES
from app.sources.errors import SourceError
from app.sources.fixture import LocalFixtureSource
from app.sources.github import GitHubSource
import app.sources.github as github_module
from app.tools.dispatch import ToolDispatcher
from app.tools.registry import build_tool_specs


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def test_tool_specs_schema_compatibility() -> None:
    specs = build_tool_specs()
    assert len(specs) == 8

    forbidden_keys = ["$ref", "anyOf", "oneOf", "additionalProperties"]

    for spec in specs:
        spec_str = json.dumps(spec.parameters)
        for key in forbidden_keys:
            assert f'"{key}"' not in spec_str, f"ToolSpec '{spec.name}' contains forbidden JSON schema key '{key}'"
        assert spec.parameters.get("type") == "object"
        assert isinstance(spec.parameters.get("properties"), dict)


def test_dispatcher_executes_all_registered_tools() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    store = EvidenceStore(audit_run_id="run-dispatch-test", commit_sha="d" * 40)
    dispatcher = ToolDispatcher(source=source, evidence=store)

    specs = build_tool_specs()
    for spec in specs:
        args: dict[str, Any] = {}
        if spec.name == "read_file":
            args = {"path": "pyproject.toml"}
        elif spec.name == "search_files":
            args = {"pattern": "releaseguard"}

        call = ToolCall(name=spec.name, args=args, call_id=f"test:{spec.name}")
        result = dispatcher.execute(call)

        assert result.ok is True, f"Tool {spec.name} failed: {result.error}"
        assert result.tool == spec.name
        assert len(result.evidence_ids) == 1
        assert result.error is None
        assert result.duration_ms >= 0


def test_dispatcher_returns_evidence_ids_in_result_dictionary() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    store = EvidenceStore(audit_run_id="run-ev-test", commit_sha="d" * 40)
    dispatcher = ToolDispatcher(source=source, evidence=store)

    specs = build_tool_specs()
    for spec in specs:
        args: dict[str, Any] = {}
        if spec.name == "read_file":
            args = {"path": "pyproject.toml"}
        elif spec.name == "search_files":
            args = {"pattern": "releaseguard"}

        call = ToolCall(name=spec.name, args=args, call_id=f"test:{spec.name}")
        result = dispatcher.execute(call)

        assert result.ok is True
        assert "evidence_ids" in result.result
        assert result.result["evidence_ids"] == result.evidence_ids
        assert len(result.result["evidence_ids"]) == 1


def test_dispatcher_handles_unknown_tool_gracefully() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    store = EvidenceStore(audit_run_id="run-test", commit_sha="d" * 40)
    dispatcher = ToolDispatcher(source=source, evidence=store)

    call = ToolCall(name="non_existent_tool", args={}, call_id="test:unknown")
    result = dispatcher.execute(call)

    assert result.ok is False
    assert result.error is not None
    assert "Unknown tool" in result.error
    assert len(result.evidence_ids) == 0


def test_dispatcher_handles_invalid_arguments_gracefully() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    store = EvidenceStore(audit_run_id="run-test", commit_sha="d" * 40)
    dispatcher = ToolDispatcher(source=source, evidence=store)

    # 1. read_file missing path
    res1 = dispatcher.execute(ToolCall(name="read_file", args={}, call_id="1"))
    assert res1.ok is False
    assert "required argument" in res1.error

    # 2. search_files missing pattern
    res2 = dispatcher.execute(ToolCall(name="search_files", args={}, call_id="2"))
    assert res2.ok is False
    assert "required argument" in res2.error

    # 3. read_file path traversal
    res3 = dispatcher.execute(ToolCall(name="read_file", args={"path": "../case.json"}, call_id="3"))
    assert res3.ok is False
    assert "escape" in res3.error.lower() or "forbidden" in res3.error.lower()

    # 4. read_file invalid type for start_line
    res4 = dispatcher.execute(ToolCall(name="read_file", args={"path": "pyproject.toml", "start_line": "not_an_int"}, call_id="4"))
    assert res4.ok is False
    assert "start_line" in res4.error


def test_dispatcher_build_report_and_test_report_formatting() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    store = EvidenceStore(audit_run_id="run-test-reports", commit_sha="e" * 40)
    dispatcher = ToolDispatcher(source=source, evidence=store)

    res_test = dispatcher.execute(ToolCall(name="get_test_report", args={}, call_id="t1"))
    assert res_test.ok is True
    assert "test_report" in res_test.result

    res_build = dispatcher.execute(ToolCall(name="get_build_report", args={}, call_id="b1"))
    assert res_build.ok is True
    assert "build_report" in res_build.result


def test_github_source_guarantees_readonly_http_get_only() -> None:
    requested_methods: list[str] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requested_methods.append(request.method)
        path = str(request.url.path).rstrip("/")

        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": "1234567890123456789012345678901234567890"}})
        elif path.endswith("/repos/octocat/Hello-World"):
            return httpx.Response(200, json={"default_branch": "main", "description": "test repo", "topics": []})
        elif path.endswith("/branches"):
            return httpx.Response(200, json=[{"name": "main"}])
        elif path.endswith("/tags"):
            return httpx.Response(200, json=[])
        elif path.endswith("/releases"):
            return httpx.Response(200, json=[])
        elif path.endswith("/git/trees/1234567890123456789012345678901234567890"):
            return httpx.Response(200, json={"tree": [{"path": "README.md", "type": "blob", "size": 100}]})
        elif path.endswith("/contents/README.md"):
            return httpx.Response(
                200,
                json={"type": "file", "encoding": "base64", "content": "SGVsbG8gV29ybGQ="},
            )
        elif path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    gh_source = GitHubSource(repo_url="https://github.com/octocat/Hello-World", token="test-token", transport=transport)

    resolved = gh_source.resolve_ref("main")
    assert resolved.commit_sha == "1234567890123456789012345678901234567890"

    metadata = gh_source.get_repository_metadata()
    assert metadata["default_branch"] == "main"

    tree = gh_source.get_tree()
    assert len(tree) == 1
    assert tree[0].path == "README.md"

    fslice = gh_source.read_file("README.md")
    assert fslice.content == "Hello World"

    runs = gh_source.get_workflow_runs()
    assert runs == []

    # Assert that EVERY HTTP request made by GitHubSource used method GET
    assert len(requested_methods) > 0
    assert all(method == "GET" for method in requested_methods)

    # Static analysis check: ensure github.py source code contains NO modifying HTTP methods
    src = inspect.getsource(github_module)
    forbidden_write_patterns = [
        r"\.post\(",
        r"\.put\(",
        r"\.patch\(",
        r"\.delete\(",
        r"\.request\(",
    ]
    for pattern in forbidden_write_patterns:
        matches = re.findall(pattern, src)
        assert not matches, f"Found forbidden write method call in app/sources/github.py matching {pattern}"


def test_github_source_requires_resolve_ref_before_content_access() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    gh_source = GitHubSource(repo_url="https://github.com/octocat/Hello-World", transport=transport)

    with pytest.raises(SourceError, match="must be resolved"):
        gh_source.get_tree()

    with pytest.raises(SourceError, match="must be resolved"):
        gh_source.read_file("pyproject.toml")

    with pytest.raises(SourceError, match="must be resolved"):
        gh_source.search_files("pattern")


def test_github_source_binds_all_content_queries_to_resolved_commit_sha() -> None:
    expected_sha = "9999888877776666555544443333222211110000"
    intercepted_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        intercepted_requests.append(request)
        path = str(request.url.path).rstrip("/")

        if path.endswith("/git/ref/tags/v1.0.0"):
            return httpx.Response(200, json={"object": {"sha": expected_sha}})
        elif path.endswith(f"/git/trees/{expected_sha}"):
            return httpx.Response(200, json={"tree": [{"path": "src/main.py", "type": "blob", "size": 50}]})
        elif path.endswith("/contents/src/main.py"):
            assert request.url.params.get("ref") == expected_sha
            return httpx.Response(
                200,
                json={"type": "file", "encoding": "base64", "content": "cHJpbnQoJ2hpJyk="},
            )
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    gh_source = GitHubSource(repo_url="https://github.com/octocat/Hello-World", transport=transport)

    resolved = gh_source.resolve_ref("v1.0.0")
    assert resolved.commit_sha == expected_sha
    assert resolved.ref_type == "tag"

    tree = gh_source.get_tree()
    assert len(tree) == 1
    assert tree[0].path == "src/main.py"

    slice_res = gh_source.read_file("src/main.py")
    assert slice_res.content == "print('hi')"


def test_github_source_resolve_ref_branch_priority() -> None:
    branch_sha = "1111111111111111111111111111111111111111"
    commit_sha = "2222222222222222222222222222222222222222"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url.path).rstrip("/")
        if path.endswith("/branches/release-v2"):
            return httpx.Response(200, json={"commit": {"sha": branch_sha}})
        elif path.endswith("/commits/release-v2"):
            return httpx.Response(200, json={"sha": commit_sha})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    gh_source = GitHubSource(repo_url="https://github.com/octocat/Hello-World", transport=transport)

    resolved = gh_source.resolve_ref("release-v2")
    assert resolved.commit_sha == branch_sha
    assert resolved.ref_type == "branch"


def test_github_source_search_files_caps_at_max_limit() -> None:
    read_count = 0
    test_sha = "a" * 40

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal read_count
        path = str(request.url.path).rstrip("/")
        if path.endswith("/branches/main"):
            return httpx.Response(200, json={"commit": {"sha": test_sha}})
        elif path.endswith(f"/git/trees/{test_sha}"):
            # 60 files in repository tree
            tree_entries = [{"path": f"src/mod_{i}.py", "type": "blob", "size": 10} for i in range(60)]
            return httpx.Response(200, json={"tree": tree_entries})
        elif "/contents/" in path:
            read_count += 1
            return httpx.Response(
                200,
                json={"type": "file", "encoding": "base64", "content": "VEFSR0VUX1ZBUiA9IDE="},
            )
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    gh_source = GitHubSource(repo_url="https://github.com/octocat/Hello-World", transport=transport)

    gh_source.resolve_ref("main")
    hits = gh_source.search_files("TARGET_VAR")

    assert read_count == MAX_GITHUB_SEARCH_FILES
    assert len(hits) == MAX_GITHUB_SEARCH_FILES
