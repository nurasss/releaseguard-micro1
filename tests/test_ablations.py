# path: tests/test_ablations.py
import json
from pathlib import Path

from app.config import Settings
from app.llm.types import LLMResponse, Usage
from app.orchestration.runner import AuditRunner
from app.schemas.enums import Decision, VerificationStatus
from tests.test_baseline_agent import FakeLLMClient


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "runs",
        db_path=tmp_path / "test_db.sqlite3",
        trajectories_dir=tmp_path / "trajectories",
        model_id="gemini-2.5-flash",
    )


def _plan_resp() -> LLMResponse:
    return LLMResponse(
        text=json.dumps({"audit_plan": {"areas": ["ci"], "questions": [], "required_tools": []}}),
        tool_calls=[],
        usage=Usage(prompt_tokens=30, output_tokens=10, total_tokens=40),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )


def _explore_resp() -> LLMResponse:
    return LLMResponse(
        text="Explored enough.",
        tool_calls=[],
        usage=Usage(prompt_tokens=50, output_tokens=10, total_tokens=60),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )


def _findings_resp(findings: list[dict]) -> LLMResponse:
    return LLMResponse(
        text=json.dumps({"findings": findings}),
        tool_calls=[],
        usage=Usage(prompt_tokens=80, output_tokens=20, total_tokens=100),
        finish_reason="STOP",
        latency_ms=15,
        retries=0,
        model_id="fake-model",
    )


def test_no_verifier_ablation_skips_verification_and_trusts_analyzer(tmp_path: Path) -> None:
    high_finding = {
        "category": "ci",
        "title": "Suspicious workflow trigger",
        "severity": "high",
        "claim": "Release workflow may not cover the release branch.",
        "confidence": 0.7,
        "evidence_ids": [],
        "recommended_action": "Double-check the trigger.",
    }
    # Only 3 responses queued: plan, explore, findings. No verifier calls should be
    # made under this ablation — if they were, FakeLLMClient would raise "ran out of
    # queued responses" and the test would fail with that error instead.
    fake_llm = FakeLLMClient([_plan_resp(), _explore_resp(), _findings_resp([high_finding])])
    runner = AuditRunner(settings=_settings(tmp_path), llm_factory=lambda: fake_llm)

    outcome = runner.run_case(case_dir=CASES_DIR / "case_01", mode="final", ablation="no_verifier")

    assert outcome.run.status.value == "completed"
    finding = next(f for f in outcome.report.findings if f.id == "F-001")
    assert finding.verification_status == VerificationStatus.confirmed
    assert outcome.report.verifications == []
    assert any("no_verifier" in lim for lim in outcome.report.limitations)


def test_no_deterministic_checks_ablation_skips_checks(tmp_path: Path) -> None:
    low_finding = {
        "category": "docs",
        "title": "Minor doc gap",
        "severity": "low",
        "claim": "Changelog entry missing.",
        "confidence": 0.6,
        "evidence_ids": [],
        "recommended_action": "Add changelog entry.",
    }
    fake_llm = FakeLLMClient([_plan_resp(), _explore_resp(), _findings_resp([low_finding])])
    runner = AuditRunner(settings=_settings(tmp_path), llm_factory=lambda: fake_llm)

    outcome = runner.run_case(
        case_dir=CASES_DIR / "case_01", mode="final", ablation="no_deterministic_checks"
    )

    assert outcome.report.deterministic_checks == []


def test_no_evidence_enforcement_ablation_keeps_unsupported_critical(tmp_path: Path) -> None:
    critical_no_evidence = {
        "category": "ci",
        "title": "Alleged CI failure",
        "severity": "critical",
        "claim": "CI is claimed to be failing but no evidence was cited.",
        "confidence": 0.5,
        "evidence_ids": [],
        "recommended_action": "Investigate CI status.",
    }
    verification_resp = LLMResponse(
        text=json.dumps(
            {
                "finding_id": "F-001",
                "status": "uncertain",
                "confidence": 0.3,
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "reason_summary": "No evidence was actually cited for this claim.",
            }
        ),
        tool_calls=[],
        usage=Usage(prompt_tokens=40, output_tokens=10, total_tokens=50),
        finish_reason="STOP",
        latency_ms=10,
        retries=0,
        model_id="fake-model",
    )
    fake_llm = FakeLLMClient(
        [
            _plan_resp(),
            _explore_resp(),
            _findings_resp([critical_no_evidence]),
            _explore_resp(),  # verifier's own bounded tool loop, no extra calls
            verification_resp,
        ]
    )
    runner = AuditRunner(settings=_settings(tmp_path), llm_factory=lambda: fake_llm)

    # Baseline behavior (no ablation): this finding must be rejected by the Analyzer's
    # mandatory evidence rule and never reach report.findings.
    fake_llm_default = FakeLLMClient([_plan_resp(), _explore_resp(), _findings_resp([critical_no_evidence])])
    runner_default = AuditRunner(settings=_settings(tmp_path), llm_factory=lambda: fake_llm_default)
    default_outcome = runner_default.run_case(case_dir=CASES_DIR / "case_01", mode="final")
    assert all(f.id != "F-001" for f in default_outcome.report.findings)
    assert any(f.id == "F-001" for f in default_outcome.report.rejected_findings)

    # With the ablation, the same finding is let through instead.
    outcome = runner.run_case(
        case_dir=CASES_DIR / "case_01", mode="final", ablation="no_evidence_enforcement"
    )
    assert any(f.id == "F-001" for f in outcome.report.findings)
    assert any("no_evidence_enforcement" in lim for lim in outcome.report.limitations)
