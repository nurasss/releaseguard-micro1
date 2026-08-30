# path: tests/test_runner.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.cli import main
from app.config import Settings
from app.llm.errors import LLMServerError
from app.llm.types import LLMResponse, ToolCall, Usage
from app.llm.xai import XAIClient
from app.orchestration.runner import AuditRunner
from app.schemas.enums import Decision, RunStatus, VerificationStatus, VerifierStatus
from app.sources.fixture import LocalFixtureSource
from app.sources.github import GitHubSource
from app.storage.db import connect, init_db
from app.storage.repository import AuditRepository
from tests.test_baseline_agent import FakeLLMClient


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
FIXTURE_SHAS = json.loads((CASES_DIR / "FIXTURE_SHAS.json").read_text(encoding="utf-8"))


def test_runner_selects_xai_client() -> None:
    settings = Settings(
        llm_provider="xai",
        model_id="grok-4.6",
        xai_api_key="test-xai-key",
        xai_min_request_interval_ms=25,
        xai_reasoning_effort="medium",
    )
    client = AuditRunner(settings=settings)._get_llm()
    assert isinstance(client, XAIClient)
    assert client.model_id == "grok-4.6"
    assert client.min_request_interval_ms == 25
    assert client.reasoning_effort == "medium"
    client.close()


def test_runner_full_successful_case_run(tmp_path: Path) -> None:
    db_path = tmp_path / "test_db.sqlite3"
    data_dir = tmp_path / "runs"
    trajectories_dir = tmp_path / "trajectories"

    settings = Settings(
        data_dir=data_dir,
        db_path=db_path,
        trajectories_dir=trajectories_dir,
        model_id="gemini-2.5-flash",
    )

    # Prepare FakeLLMClient responses
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

    fake_llm = FakeLLMClient([resp1, resp2, resp3])
    runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)

    fixed_timestamp = "2026-08-29T12:00:00Z"
    outcome = runner.run_case(
        case_dir=CASES_DIR / "case_01",
        mode="baseline",
        timestamp=fixed_timestamp,
    )

    run = outcome.run
    report = outcome.report

    # Assertions on Run and Report
    assert run.status == RunStatus.completed
    assert run.final_decision == Decision.GO
    assert run.commit_sha == FIXTURE_SHAS["case_01"]
    assert report.commit_sha == FIXTURE_SHAS["case_01"]
    assert report.decision == Decision.GO

    # Findings verification
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.id == "F-001"
    assert finding.origin == "baseline"
    assert finding.evidence_ids == ["E-001"]

    # Evidence verification: all accumulated evidence is in report.evidence
    assert len(report.evidence) == 1
    assert report.evidence[0].id == "E-001"

    # Artifacts verification
    assert (outcome.artifacts_dir / "report.json").exists()
    assert (outcome.artifacts_dir / "run.json").exists()
    assert (trajectories_dir / f"{run.id}.jsonl").exists()

    # Database verification
    conn = connect(db_path)
    init_db(conn)
    repo = AuditRepository(conn)
    db_run = repo.get_run(run.id)
    assert db_run is not None
    assert db_run.id == run.id
    assert db_run.status == RunStatus.completed
    db_findings = repo.get_findings(run.id)
    assert len(db_findings) == 1
    assert db_findings[0].id == "F-001"
    db_evidence = repo.get_evidence(run.id)
    assert len(db_evidence) == 1
    db_steps = repo.get_agent_steps(run.id)
    assert len(db_steps) > 0
    conn.close()


def test_runner_failed_run_writes_artifacts_and_does_not_crash(tmp_path: Path) -> None:
    db_path = tmp_path / "test_db.sqlite3"
    data_dir = tmp_path / "runs"
    trajectories_dir = tmp_path / "trajectories"

    settings = Settings(
        data_dir=data_dir,
        db_path=db_path,
        trajectories_dir=trajectories_dir,
    )

    fake_llm = FakeLLMClient([LLMServerError("LLM unavailable")])
    runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)

    outcome = runner.run_case(
        case_dir=CASES_DIR / "case_01",
        mode="baseline",
    )

    assert outcome.run.status == RunStatus.failed
    assert outcome.report.decision == Decision.REVIEW
    assert "LLM unavailable" in outcome.report.executive_summary
    assert (outcome.artifacts_dir / "report.json").exists()
    assert (outcome.artifacts_dir / "run.json").exists()


def test_runner_unknown_ref_fails_gracefully(tmp_path: Path) -> None:
    db_path = tmp_path / "test_db.sqlite3"
    data_dir = tmp_path / "runs"
    trajectories_dir = tmp_path / "trajectories"

    settings = Settings(
        data_dir=data_dir,
        db_path=db_path,
        trajectories_dir=trajectories_dir,
    )

    # Use mock transport so network is never accessed
    mock_transport = httpx.MockTransport(lambda r: httpx.Response(404, json={}))
    mock_gh_source = GitHubSource(
        repo_url="https://github.com/octocat/Hello-World",
        transport=mock_transport,
    )

    runner = AuditRunner(settings=settings)
    outcome = runner._execute_audit(
        source=mock_gh_source,
        repository_url="https://github.com/octocat/Hello-World",
        ref="non_existent_ref_99999",
        mode="baseline",
        timestamp="2026-08-29T12:00:00Z",
    )

    assert outcome.run.status == RunStatus.failed
    assert outcome.report.decision == Decision.REVIEW
    assert "Ref resolution failed" in outcome.report.executive_summary
    assert (outcome.artifacts_dir / "report.json").exists()
    assert (outcome.artifacts_dir / "run.json").exists()


def test_runner_rejects_private_repository_before_content_access(tmp_path: Path) -> None:
    case_dir = tmp_path / "private_case"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    (case_dir / "repo" / ".env").write_text("PASSWORD=do-not-read\n", encoding="utf-8")
    (case_dir / "artifacts" / "repository_metadata.json").write_text(
        json.dumps({"private": True, "default_branch": "main", "branches": ["main"]}),
        encoding="utf-8",
    )

    settings = Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "audit.sqlite3",
        trajectories_dir=tmp_path / "trajectories",
    )
    outcome = AuditRunner(settings=settings).run_case(case_dir=case_dir, mode="baseline")

    assert outcome.run.status == RunStatus.failed
    assert "Private repositories are not supported" in outcome.report.executive_summary
    assert not (outcome.artifacts_dir / "snapshot.json").exists()
    assert "do-not-read" not in (outcome.artifacts_dir / "report.json").read_text(encoding="utf-8")


def test_runner_integrity_violations_returned_without_crashing(tmp_path: Path) -> None:
    db_path = tmp_path / "test_db.sqlite3"
    data_dir = tmp_path / "runs"
    trajectories_dir = tmp_path / "trajectories"

    settings = Settings(
        data_dir=data_dir,
        db_path=db_path,
        trajectories_dir=trajectories_dir,
    )

    # Return a critical finding with NO evidence -> causes integrity violation
    bad_payload = {
        "decision": "NO-GO",
        "executive_summary": "Critical blocker found without evidence.",
        "findings": [
            {
                "category": "security",
                "title": "Severe vulnerability",
                "severity": "critical",
                "claim": "No evidence attached to critical finding.",
                "confidence": 0.99,
                "evidence_ids": [],
                "recommended_action": "Fix vulnerability.",
            }
        ],
    }
    fake_llm = FakeLLMClient(
        [
            LLMResponse(
                text=None,
                tool_calls=[],
                usage=Usage(total_tokens=10),
                finish_reason="STOP",
                latency_ms=10,
                retries=0,
                model_id="fake",
            ),
            LLMResponse(
                text=json.dumps(bad_payload),
                tool_calls=[],
                usage=Usage(total_tokens=10),
                finish_reason="STOP",
                latency_ms=10,
                retries=0,
                model_id="fake",
            ),
        ]
    )

    runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)
    outcome = runner.run_case(case_dir=CASES_DIR / "case_01", mode="baseline")

    assert outcome.run.status == RunStatus.completed
    assert len(outcome.integrity_violations) > 0
    assert any(v.code == "UNSUPPORTED_CRITICAL" for v in outcome.integrity_violations)


def test_runner_separates_audit_deadline_and_request_timeout(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "test.db",
        trajectories_dir=tmp_path / "trajectories",
        audit_deadline_s=300,
        request_timeout_s=120,
    )

    fake_resp = {
        "decision": "GO",
        "executive_summary": "Deadline separation verified",
        "findings": [],
    }
    fake_llm = FakeLLMClient(
        [
            LLMResponse(text=None, tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
            LLMResponse(text=json.dumps(fake_resp), tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
        ]
    )

    created_agents: list[Any] = []
    with patch("app.orchestration.runner.BaselineAgent", side_effect=lambda *args, **kwargs: created_agents.append(kwargs) or MagicMock(run=lambda **kw: MagicMock(status="success", findings_payload=fake_resp, usage_prompt_tokens=10, usage_output_tokens=10, usage_total_tokens=20))):
        runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)
        runner.run_case(case_dir=CASES_DIR / "case_01", mode="baseline")

    assert len(created_agents) == 1
    assert created_agents[0]["deadline_s"] == 300


def test_runner_passes_max_turns_to_agent(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "test.db",
        trajectories_dir=tmp_path / "trajectories",
    )

    fake_resp = {"decision": "GO", "executive_summary": "Max turns passed", "findings": []}
    fake_llm = FakeLLMClient(
        [
            LLMResponse(text=None, tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
            LLMResponse(text=json.dumps(fake_resp), tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
        ]
    )

    created_agents: list[Any] = []
    with patch("app.orchestration.runner.BaselineAgent", side_effect=lambda *args, **kwargs: created_agents.append(kwargs) or MagicMock(run=lambda **kw: MagicMock(status="success", findings_payload=fake_resp, usage_prompt_tokens=10, usage_output_tokens=10, usage_total_tokens=20))):
        runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)
        runner.run_case(case_dir=CASES_DIR / "case_01", mode="baseline", max_turns=7)

    assert len(created_agents) == 1
    assert created_agents[0]["max_turns"] == 7


def test_runner_final_mode_full_pipeline(tmp_path: Path) -> None:
    db_path = tmp_path / "test_db.sqlite3"
    data_dir = tmp_path / "runs"
    trajectories_dir = tmp_path / "trajectories"

    settings = Settings(
        data_dir=data_dir,
        db_path=db_path,
        trajectories_dir=trajectories_dir,
        model_id="gemini-2.5-flash",
    )

    plan_resp = LLMResponse(
        text=json.dumps({"audit_plan": {"areas": ["ci", "tests"], "questions": [], "required_tools": []}}),
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    explore_resp = LLMResponse(
        text="Explored enough given the deterministic check results.",
        tool_calls=[],
        usage=Usage(prompt_tokens=50, output_tokens=10, total_tokens=60),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    findings_payload = {
        "findings": [
            {
                "category": "docs",
                "title": "Minor doc gap",
                "severity": "low",
                "claim": "Changelog entry is missing for a cosmetic change.",
                "confidence": 0.6,
                "evidence_ids": [],
                "recommended_action": "Add changelog entry.",
            },
            {
                "category": "ci",
                "title": "Release workflow may not cover this branch",
                "severity": "high",
                "claim": "The release workflow trigger looks narrower than expected.",
                "confidence": 0.7,
                "evidence_ids": [],
                "recommended_action": "Double-check the workflow trigger before release.",
            },
        ]
    }
    findings_resp = LLMResponse(
        text=json.dumps(findings_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=80, output_tokens=30, total_tokens=110),
        finish_reason="STOP",
        latency_ms=20,
        retries=0,
        model_id="fake-model",
    )
    verifier_explore_resp = LLMResponse(
        text="No extra evidence needed.",
        tool_calls=[],
        usage=Usage(prompt_tokens=40, output_tokens=5, total_tokens=45),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    verification_payload = {
        "finding_id": "F-002",
        "status": "confirmed",
        "confidence": 0.85,
        "supporting_evidence": [],
        "contradicting_evidence": [],
        "reason_summary": "The workflow trigger does not cover the release branch.",
    }
    verification_resp = LLMResponse(
        text=json.dumps(verification_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=60, output_tokens=20, total_tokens=80),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )

    fake_llm = FakeLLMClient(
        [plan_resp, explore_resp, findings_resp, verifier_explore_resp, verification_resp]
    )
    runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)

    outcome = runner.run_case(case_dir=CASES_DIR / "case_01", mode="final")

    run = outcome.run
    report = outcome.report

    assert run.status == RunStatus.completed
    assert report.mode == "final"
    # Deterministic checks actually ran (DC-01..DC-10 against the real fixture).
    assert len(report.deterministic_checks) > 0

    finding_ids = {f.id: f for f in report.findings}
    assert "F-001" in finding_ids
    assert finding_ids["F-001"].verification_status == VerificationStatus.pending  # low severity, never verified
    assert "F-002" in finding_ids
    assert finding_ids["F-002"].verification_status == VerificationStatus.confirmed

    assert len(report.verifications) == 1
    assert report.verifications[0].finding_id == "F-002"
    assert report.verifications[0].status == VerifierStatus.confirmed

    # Confirmed high finding with no confirmed critical -> REVIEW per Decision Policy.
    assert report.decision == Decision.REVIEW

    assert (outcome.artifacts_dir / "report.json").exists()
    assert (outcome.artifacts_dir / "run.json").exists()
    assert (outcome.artifacts_dir / "report.md").exists()

    conn = connect(db_path)
    init_db(conn)
    repo = AuditRepository(conn)
    db_verifications = repo.get_verifications(run.id)
    assert len(db_verifications) == 1
    conn.close()


def test_cli_audit_case_execution(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out_dir = tmp_path / "cli_runs"
    db_file = tmp_path / "cli.sqlite3"

    # Mock AuditRunner to return fake outcome without network
    resp = {
        "decision": "GO",
        "executive_summary": "CLI test passed",
        "findings": [],
    }
    fake_llm = FakeLLMClient(
        [
            LLMResponse(text=None, tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
            LLMResponse(text=json.dumps(resp), tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
        ]
    )

    with patch("app.orchestration.runner.AuditRunner._get_llm", return_value=fake_llm):
        ret_code = main(
            [
                "audit",
                "--case",
                str(CASES_DIR / "case_01"),
                "--mode",
                "baseline",
                "--max-turns",
                "8",
                "--deadline",
                "250",
                "--out",
                str(out_dir),
                "--db",
                str(db_file),
            ]
        )

    assert ret_code == 0
    captured = capsys.readouterr()
    assert "ReleaseGuard Audit Result" in captured.out
    assert "GO" in captured.out


def test_cli_deadline_flag_modifies_audit_deadline_s_not_request_timeout_s(tmp_path: Path) -> None:
    fake_resp = {"decision": "GO", "executive_summary": "CLI deadline test", "findings": []}
    fake_llm = FakeLLMClient(
        [
            LLMResponse(text=None, tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
            LLMResponse(text=json.dumps(fake_resp), tool_calls=[], usage=Usage(total_tokens=10), finish_reason="STOP", latency_ms=10, retries=0, model_id="fake"),
        ]
    )

    captured_settings: list[Settings] = []

    def mock_run_case(self, case_dir, mode, max_turns=None, timestamp=None):
        captured_settings.append(self.settings)
        return MagicMock(run=MagicMock(status=RunStatus.completed, id="aud_123", repository_url="repo", requested_ref="main", commit_sha="abc", mode="baseline"), report=MagicMock(decision=Decision.GO, findings=[], evidence=[], runtime_ms=10, estimated_cost_usd=0.0), artifacts_dir=tmp_path, integrity_violations=[])

    with patch("app.orchestration.runner.AuditRunner.run_case", mock_run_case):
        ret = main(["audit", "--case", str(CASES_DIR / "case_01"), "--deadline", "450"])

    assert ret == 0
    assert len(captured_settings) == 1
    assert captured_settings[0].audit_deadline_s == 450
    assert captured_settings[0].request_timeout_s == 120  # Unchanged!


def test_cli_no_subcommand_returns_one(capsys: pytest.CaptureFixture) -> None:
    ret = main([])
    assert ret == 1
