# path: tests/test_it5_subagents.py
import json
from pathlib import Path

from app.agents.experimental.subagents import (
    CategorySubagent,
    CiSubagent,
    SecuritySubagent,
    TestSubagent,
    run_it5_subagents,
)
from app.evidence.store import EvidenceStore
from app.llm.errors import LLMServerError
from app.llm.types import LLMResponse, Usage
from app.orchestration.runner import AuditRunner
from app.schemas.enums import FindingCategory, RunStatus
from app.sources.fixture import LocalFixtureSource
from app.tools.dispatch import ToolDispatcher
from app.trajectory.logger import TrajectoryLogger
from tests.test_baseline_agent import FakeLLMClient


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def _make_env(tmp_path: Path, run_id: str):
    source = LocalFixtureSource(CASES_DIR / "case_01")
    resolved_ref = source.resolve_ref("main")
    store = EvidenceStore(audit_run_id=run_id, commit_sha=resolved_ref.commit_sha)
    dispatcher = ToolDispatcher(source=source, evidence=store)
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=tmp_path / "trajectories")
    return source, resolved_ref, store, dispatcher, logger


def _plan_response(areas: list[str]) -> LLMResponse:
    plan_payload = {
        "audit_plan": {
            "areas": areas,
            "questions": [f"Is {areas[0]} healthy?"],
            "required_tools": ["get_workflow_runs"],
        }
    }
    return LLMResponse(
        text=json.dumps(plan_payload),
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )


def _no_tools_response() -> LLMResponse:
    return LLMResponse(
        text="Done exploring, no tools needed.",
        tool_calls=[],
        usage=Usage(prompt_tokens=10, output_tokens=5, total_tokens=15),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )


def _findings_response(findings: list[dict]) -> LLMResponse:
    return LLMResponse(
        text=json.dumps({"findings": findings}),
        tool_calls=[],
        usage=Usage(prompt_tokens=20, output_tokens=10, total_tokens=30),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )


def _finding_payload(category: str, severity: str = "info", evidence_ids: list[str] | None = None) -> dict:
    return {
        "category": category,
        "title": f"A {category} finding",
        "severity": severity,
        "claim": f"Observed something about {category}.",
        "confidence": 0.8,
        "evidence_ids": evidence_ids or [],
        "recommended_action": "No action needed." if severity == "info" else "Investigate.",
    }


# ---------------------------------------------------------------------------
# Individual subagent behavior
# ---------------------------------------------------------------------------


def test_ci_subagent_plan_explore_findings_accepts_matching_category(tmp_path: Path) -> None:
    run_id = "aud_it5_ci_success"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient(
        [
            _plan_response(["ci"]),
            _no_tools_response(),
            _findings_response([_finding_payload("ci")]),
        ]
    )
    subagent = CiSubagent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = subagent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert len(outcome.findings) == 1
    assert outcome.findings[0].category == FindingCategory.ci
    assert outcome.rejected_findings == []

    # First call is the schema-constrained plan call with no tools.
    first_call = fake_llm.recorded_calls[0]
    assert first_call["tools"] is None
    assert first_call["response_schema"] is not None


def test_security_subagent_rejects_category_mismatch(tmp_path: Path) -> None:
    run_id = "aud_it5_security_mismatch"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient(
        [
            _plan_response(["security"]),
            _no_tools_response(),
            _findings_response(
                [
                    _finding_payload("security"),
                    _finding_payload("ci"),  # off-scope for the security subagent
                ]
            ),
        ]
    )
    subagent = SecuritySubagent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = subagent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert len(outcome.findings) == 1
    assert outcome.findings[0].category == FindingCategory.security
    assert len(outcome.rejected_findings) == 1
    assert outcome.rejected_findings[0]["reason"] == "category_mismatch"
    assert outcome.rejected_findings[0]["finding"]["category"] == "ci"


def test_test_subagent_rejects_critical_finding_without_evidence(tmp_path: Path) -> None:
    run_id = "aud_it5_test_no_evidence"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient(
        [
            _plan_response(["tests"]),
            _no_tools_response(),
            _findings_response(
                [
                    _finding_payload("tests", severity="critical", evidence_ids=[]),
                    _finding_payload("tests", severity="info"),
                ]
            ),
        ]
    )
    subagent = TestSubagent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
    )

    outcome = subagent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "success"
    assert len(outcome.findings) == 1
    assert outcome.findings[0].severity.value == "info"
    assert len(outcome.rejected_findings) == 1
    assert outcome.rejected_findings[0]["reason"] == "no_evidence_for_critical"


def test_category_subagent_plan_phase_failure_fails_whole_run(tmp_path: Path) -> None:
    run_id = "aud_it5_plan_fail"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    fake_llm = FakeLLMClient([LLMServerError("Upstream 500 error")])
    subagent = CategorySubagent(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        category=FindingCategory.ci,
    )

    outcome = subagent.run(
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
    )

    assert outcome.status == "failed"
    assert "Upstream 500 error" in (outcome.failure_reason or "")
    assert outcome.findings == []


# ---------------------------------------------------------------------------
# Combiner: run_it5_subagents
# ---------------------------------------------------------------------------


def test_run_it5_subagents_combines_and_renumbers_ids(tmp_path: Path) -> None:
    run_id = "aud_it5_combine"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    # ci subagent: plan, explore, findings (2 findings)
    # security subagent: plan, explore, findings (1 finding)
    # tests subagent: plan, explore, findings (1 finding)
    fake_llm = FakeLLMClient(
        [
            _plan_response(["ci"]),
            _no_tools_response(),
            _findings_response([_finding_payload("ci"), _finding_payload("ci")]),
            _plan_response(["security"]),
            _no_tools_response(),
            _findings_response([_finding_payload("security")]),
            _plan_response(["tests"]),
            _no_tools_response(),
            _findings_response([_finding_payload("tests")]),
        ]
    )

    outcome = run_it5_subagents(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deterministic_checks=[],
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
        deadline_s=300,
    )

    assert outcome.status == "success"
    assert outcome.failure_reason is None
    assert len(outcome.findings) == 4

    ids = [f.id for f in outcome.findings]
    assert ids == ["F-001", "F-002", "F-003", "F-004"]
    assert len(set(ids)) == len(ids)  # no duplicates

    categories = [f.category for f in outcome.findings]
    assert categories == [
        FindingCategory.ci,
        FindingCategory.ci,
        FindingCategory.security,
        FindingCategory.tests,
    ]

    # Usage totals are summed across all three subagents.
    expected_prompt = 3 * (30 + 10 + 20)
    expected_output = 3 * (10 + 5 + 10)
    expected_total = 3 * (40 + 15 + 30)
    assert outcome.usage_prompt_tokens == expected_prompt
    assert outcome.usage_output_tokens == expected_output
    assert outcome.usage_total_tokens == expected_total
    assert outcome.turns == 9  # 3 turns per subagent x 3 subagents


def test_run_it5_subagents_hard_failure_in_one_subagent_fails_combined_outcome(tmp_path: Path) -> None:
    run_id = "aud_it5_hard_failure"
    source, resolved_ref, store, dispatcher, logger = _make_env(tmp_path, run_id)

    # ci subagent succeeds fully; security subagent's plan call fails outright;
    # tests subagent succeeds fully. All three still run.
    fake_llm = FakeLLMClient(
        [
            _plan_response(["ci"]),
            _no_tools_response(),
            _findings_response([_finding_payload("ci")]),
            LLMServerError("Upstream 500 error"),
            _plan_response(["tests"]),
            _no_tools_response(),
            _findings_response([_finding_payload("tests")]),
        ]
    )

    outcome = run_it5_subagents(
        llm=fake_llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=store,
        logger=logger,
        deterministic_checks=[],
        repository_url="https://github.com/test/repo",
        resolved_ref=resolved_ref,
        audit_run_id=run_id,
        deadline_s=300,
    )

    assert outcome.status == "failed"
    assert "security" in outcome.failure_reason
    assert "Upstream 500 error" in outcome.failure_reason
    assert outcome.findings == []


# ---------------------------------------------------------------------------
# End-to-end via AuditRunner
# ---------------------------------------------------------------------------


def test_runner_it5_subagents_ablation_end_to_end(tmp_path: Path) -> None:
    from app.config import Settings

    settings = Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "test_db.sqlite3",
        trajectories_dir=tmp_path / "trajectories",
        model_id="gemini-2.5-flash",
    )

    fake_llm = FakeLLMClient(
        [
            _plan_response(["ci"]),
            _no_tools_response(),
            _findings_response([_finding_payload("ci")]),
            _plan_response(["security"]),
            _no_tools_response(),
            _findings_response([_finding_payload("security")]),
            _plan_response(["tests"]),
            _no_tools_response(),
            _findings_response([_finding_payload("tests")]),
        ]
    )

    runner = AuditRunner(settings=settings, llm_factory=lambda: fake_llm)
    outcome = runner.run_case(
        case_dir=CASES_DIR / "case_01",
        mode="final",
        ablation="it5_subagents",
    )

    assert outcome.run.status == RunStatus.completed
    report = outcome.report
    assert report.mode == "final"
    assert len(report.findings) == 3

    ids = [f.id for f in report.findings]
    assert ids == ["F-001", "F-002", "F-003"]
    assert len(set(ids)) == len(ids)

    assert (outcome.artifacts_dir / "report.json").exists()
    assert (outcome.artifacts_dir / "run.json").exists()
