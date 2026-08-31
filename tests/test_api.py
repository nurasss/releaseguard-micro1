# path: tests/test_api.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_repository, get_runner, get_settings
from app.api.main import app
from app.api.schemas import CreateAuditRequest
from app.config import Settings
from app.orchestration.runner import AuditRunner
from app.sources.fixture import LocalFixtureSource
from tests.test_baseline_agent import FakeLLMClient

from app.llm.types import LLMResponse, ToolCall, Usage

CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "test_db.sqlite3",
        trajectories_dir=tmp_path / "trajectories",
        model_id="gemini-2.5-flash",
    )


def _fake_llm_for_successful_run() -> FakeLLMClient:
    resp1 = LLMResponse(
        text=None,
        tool_calls=[ToolCall(name="read_file", args={"path": "pyproject.toml"}, call_id="1")],
        usage=Usage(prompt_tokens=50, output_tokens=10, total_tokens=60),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )
    resp2 = LLMResponse(
        text="Finished reading.",
        tool_calls=[],
        usage=Usage(prompt_tokens=60, output_tokens=5, total_tokens=65),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )
    final_payload = {
        "decision": "GO",
        "executive_summary": "Ready to ship.",
        "findings": [
            {
                "category": "release_metadata",
                "title": "Clean version",
                "severity": "low",
                "claim": "All checks passed.",
                "confidence": 1.0,
                "evidence_ids": ["E-001"],
                "recommended_action": "Publish release.",
            }
        ],
    }
    resp3 = LLMResponse(
        text=json.dumps(final_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=100, output_tokens=40, total_tokens=140),
        finish_reason="STOP",
        latency_ms=50,
        retries=0,
        model_id="fake-model",
    )
    return FakeLLMClient([resp1, resp2, resp3])


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    return _make_settings(tmp_path)


@pytest.fixture
def client(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # run_repository() constructs a GitHubSource internally; swap it for a
    # LocalFixtureSource-backed fake so no real network/GitHub access happens.
    class _FakeGitHubSource:
        def __new__(cls, *args, **kwargs):
            return LocalFixtureSource(CASES_DIR / "case_01")

    monkeypatch.setattr("app.orchestration.runner.GitHubSource", _FakeGitHubSource)

    fake_llm = _fake_llm_for_successful_run()

    def _override_get_settings() -> Settings:
        return api_settings

    def _override_get_runner() -> AuditRunner:
        return AuditRunner(settings=api_settings, llm_factory=lambda: fake_llm)

    app.dependency_overrides[get_settings] = _override_get_settings
    app.dependency_overrides[get_runner] = _override_get_runner
    # get_repository has settings as its own dependency; overriding
    # get_settings is enough since it re-resolves settings through Depends.

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready(client: TestClient) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


def test_create_audit_and_fetch_it(client: TestClient) -> None:
    create_resp = client.post(
        "/api/v1/audits",
        json={
            "repository_url": "https://github.com/eval/case_01",
            "ref": "v1.4.0",
            "profile": "default-release",
            # Explicit: the scripted fake LLM below covers the B1 call sequence.
            # The default-mode contract is asserted in test_default_audit_mode_is_final.
            "mode": "baseline",
        },
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    assert "audit_id" in body
    assert body["status"] == "completed"
    audit_id = body["audit_id"]

    get_resp = client.get(f"/api/v1/audits/{audit_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["audit_id"] == audit_id
    assert detail["run"]["id"] == audit_id
    assert detail["run"]["status"] == "completed"
    assert detail["report"] is not None
    assert detail["report"]["decision"] == "GO"

    findings_resp = client.get(f"/api/v1/audits/{audit_id}/findings")
    assert findings_resp.status_code == 200
    findings_body = findings_resp.json()
    assert findings_body["audit_id"] == audit_id
    assert len(findings_body["findings"]) == 1
    assert findings_body["findings"][0]["id"] == "F-001"

    trajectory_resp = client.get(f"/api/v1/audits/{audit_id}/trajectory")
    assert trajectory_resp.status_code == 200
    steps = trajectory_resp.json()
    assert isinstance(steps, list)
    assert len(steps) > 0

    report_md_resp = client.get(f"/api/v1/audits/{audit_id}/report.md")
    assert report_md_resp.status_code == 200
    assert report_md_resp.headers["content-type"].startswith("text/markdown")
    assert "# ReleaseGuard Audit" in report_md_resp.text


def test_get_audit_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/audits/aud_does_not_exist")
    assert resp.status_code == 404


def test_get_findings_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/audits/aud_does_not_exist/findings")
    assert resp.status_code == 404


def test_get_trajectory_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/audits/aud_does_not_exist/trajectory")
    assert resp.status_code == 404


def _fake_llm_for_successful_final_run() -> FakeLLMClient:
    """Analyzer plan -> explore -> findings, then Verifier explore -> verdict."""
    plan_resp = LLMResponse(
        text=json.dumps({"audit_plan": {"areas": ["ci"], "questions": [], "required_tools": []}}),
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    explore_resp = LLMResponse(
        text="Explored enough.",
        tool_calls=[],
        usage=Usage(prompt_tokens=50, output_tokens=10, total_tokens=60),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    findings_resp = LLMResponse(
        text=json.dumps(
            {
                "findings": [
                    {
                        "category": "docs",
                        "title": "Minor doc gap",
                        "severity": "low",
                        "claim": "Changelog entry missing.",
                        "confidence": 0.6,
                        "evidence_ids": [],
                        "recommended_action": "Add changelog entry.",
                    }
                ]
            }
        ),
        tool_calls=[],
        usage=Usage(prompt_tokens=80, output_tokens=20, total_tokens=100),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )
    return FakeLLMClient([plan_resp, explore_resp, findings_resp])


def test_create_audit_final_mode_runs_end_to_end(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeGitHubSource:
        def __new__(cls, *args, **kwargs):
            return LocalFixtureSource(CASES_DIR / "case_01")

    monkeypatch.setattr("app.orchestration.runner.GitHubSource", _FakeGitHubSource)

    fake_llm = _fake_llm_for_successful_final_run()

    app.dependency_overrides[get_settings] = lambda: api_settings
    app.dependency_overrides[get_runner] = lambda: AuditRunner(
        settings=api_settings, llm_factory=lambda: fake_llm
    )
    try:
        with TestClient(app) as test_client:
            resp = test_client.post(
                "/api/v1/audits",
                json={
                    "repository_url": "https://github.com/eval/case_01",
                    "ref": "v1.4.0",
                    "mode": "final",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "completed"
    finally:
        app.dependency_overrides.clear()


def test_default_audit_mode_is_final() -> None:
    """A caller that omits `mode` must get the product, not the B1 control.

    B1 is the deliberately weakened baseline kept for evaluation; serving it by
    default would misrepresent the system to any API or UI client.
    """
    request = CreateAuditRequest(repository_url="https://github.com/eval/case_01")

    assert request.mode == "final"
