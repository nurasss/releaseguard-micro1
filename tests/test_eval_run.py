# path: tests/test_eval_run.py
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.schemas.enums import Decision, SourceType
from app.schemas.evidence import Evidence
from app.schemas.findings import Finding
from app.schemas.report import AuditReport
from eval.report import generate_markdown_report, main as report_main
from eval.run import main as run_main, run_evaluation


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
GOLD_DIR = Path(__file__).resolve().parents[1] / "eval" / "gold"


def create_mock_report(case_id: str, decision: Decision = Decision.NO_GO) -> AuditReport:
    f = Finding(
        id="F-001",
        audit_run_id=f"run_{case_id}",
        category="tests",
        title=f"Sample finding for {case_id}",
        severity="critical",
        claim=f"Test failure detected in {case_id}",
        confidence=0.9,
        evidence_ids=["E-001"],
        recommended_action="Fix",
    )
    ev = Evidence(
        id="E-001",
        audit_run_id=f"run_{case_id}",
        source_type=SourceType.test_result,
        source_path="test_report.json",
        source_ref="0" * 40,
        content_hash="sha256:" + "0" * 64,
        summary="Test report summary",
        payload={},
    )
    return AuditReport(
        audit_run_id=f"run_{case_id}",
        repository_url=f"https://github.com/org/{case_id}",
        requested_ref="v1.0.0",
        commit_sha="0" * 40,
        mode="baseline",
        decision=decision,
        executive_summary=f"Audit completed for {case_id}",
        findings=[f],
        evidence=[ev],
        runtime_ms=1500,
        model_id="gemini-2.5-flash",
        prompt_version="p1",
        estimated_cost_usd=0.005,
    )


def test_dry_run_generates_valid_results_json(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Place mock reports in runs_dir
    case_ids = ["case_01", "case_02"]
    for cid in case_ids:
        case_run_dir = runs_dir / f"run_{cid}"
        case_run_dir.mkdir(parents=True, exist_ok=True)
        report = create_mock_report(cid, decision=Decision.GO if cid == "case_01" else Decision.NO_GO)
        (case_run_dir / "report.json").write_text(
            json.dumps(report.model_dump(mode="json")), encoding="utf-8"
        )

    results_payload, exit_code = run_evaluation(
        mode="baseline",
        case_ids=case_ids,
        label="test_dry_run_label",
        dry_run=True,
        cases_dir=CASES_DIR,
        gold_dir=GOLD_DIR,
        results_dir=results_dir,
        runs_dir=runs_dir,
    )

    assert exit_code == 0

    # Verify results.json structure according to Section 11 of EVALUATION_SPEC.md
    assert "meta" in results_payload
    meta = results_payload["meta"]
    assert meta["run_label"] == "test_dry_run_label"
    assert meta["mode"] == "baseline"
    assert meta["spec_version"] == "1.0"
    assert meta["frozen_at"] == "2026-08-29"
    assert meta["cases_total"] == 2
    assert meta["timeout_s"] == 300

    assert "per_case" in results_payload
    assert len(results_payload["per_case"]) == 2
    for p in results_payload["per_case"]:
        assert p["status"] == "success"
        assert "matched_blockers" in p
        assert "missed_blockers" in p
        assert "false_positives" in p
        assert "evidence_coverage" in p

    assert "aggregate" in results_payload
    agg = results_payload["aggregate"]
    assert "development" in agg
    assert "held_out" in agg
    assert "all" in agg

    saved_file = results_dir / "test_dry_run_label" / "results.json"
    assert saved_file.exists()


def test_crash_of_single_case_does_not_abort_entire_run(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    runs_dir = tmp_path / "runs"

    # Mock runner that fails on case_01 and succeeds on case_02
    mock_runner = MagicMock()

    def side_effect(case_dir, mode, ablation="none"):
        cid = Path(case_dir).name
        if cid == "case_01":
            raise RuntimeError("Case 01 crashed unexpectedly")
        outcome = MagicMock()
        outcome.run.status = "completed"
        outcome.report = create_mock_report("case_02", decision=Decision.NO_GO)
        return outcome

    mock_runner.run_case.side_effect = side_effect

    results_payload, exit_code = run_evaluation(
        mode="baseline",
        case_ids=["case_01", "case_02"],
        label="test_crash_handling",
        dry_run=False,
        cases_dir=CASES_DIR,
        gold_dir=GOLD_DIR,
        results_dir=results_dir,
        runs_dir=runs_dir,
        runner=mock_runner,
    )

    # Must return 1 due to failed case
    assert exit_code == 1

    per_case = results_payload["per_case"]
    assert len(per_case) == 2
    # Case 01 is recorded as failed
    assert per_case[0]["case_id"] == "case_01"
    assert per_case[0]["status"] == "failed"
    # Case 02 ran successfully
    assert per_case[1]["case_id"] == "case_02"
    assert per_case[1]["status"] == "success"


def test_report_generation_and_comparison(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # Run 1 results
    run1 = {
        "meta": {"run_label": "baseline_run", "mode": "baseline", "model_id": "gemini-2.5-flash", "cases_total": 2},
        "per_case": [
            {
                "case_id": "case_01",
                "decision_expected": "GO",
                "decision_actual": "GO",
                "matched_blockers": [],
                "missed_blockers": [],
                "false_positives": [],
                "evidence_coverage": 1.0,
                "blockers_total": 0,
                "runtime_ms": 1000,
                "estimated_cost": 0.01,
                "status": "success",
            }
        ],
        "aggregate": {
            "development": {"cbr": 0.5, "precision": 0.8, "f1": 0.6154, "decision_accuracy": 0.75, "evidence_coverage": 0.5, "critical_evidence_coverage": 0.5, "unsupported_critical_total": 1, "trap_hits_total": 0, "successful_run_rate": 1.0, "total_runtime_ms": 1000, "total_cost": 0.01},
            "held_out": {"cbr": 0.0, "precision": 0.0, "f1": 0.0, "decision_accuracy": 0.0, "evidence_coverage": 0.0, "critical_evidence_coverage": 0.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 0.0, "total_runtime_ms": 0, "total_cost": 0.0},
            "all": {"cbr": 0.5, "precision": 0.8, "f1": 0.6154, "decision_accuracy": 0.75, "evidence_coverage": 0.5, "critical_evidence_coverage": 0.5, "unsupported_critical_total": 1, "trap_hits_total": 0, "successful_run_rate": 1.0, "total_runtime_ms": 1000, "total_cost": 0.01},
        },
    }

    # Run 2 results
    run2 = {
        "meta": {"run_label": "final_run", "mode": "final", "model_id": "gemini-2.5-flash", "cases_total": 2},
        "per_case": [
            {
                "case_id": "case_01",
                "decision_expected": "GO",
                "decision_actual": "GO",
                "matched_blockers": [],
                "missed_blockers": [],
                "false_positives": [],
                "evidence_coverage": 1.0,
                "blockers_total": 0,
                "runtime_ms": 1200,
                "estimated_cost": 0.02,
                "status": "success",
            }
        ],
        "aggregate": {
            "development": {"cbr": 1.0, "precision": 1.0, "f1": 1.0, "decision_accuracy": 1.0, "evidence_coverage": 1.0, "critical_evidence_coverage": 1.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 1.0, "total_runtime_ms": 1200, "total_cost": 0.02},
            "held_out": {"cbr": 1.0, "precision": 1.0, "f1": 1.0, "decision_accuracy": 1.0, "evidence_coverage": 1.0, "critical_evidence_coverage": 1.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 1.0, "total_runtime_ms": 1200, "total_cost": 0.02},
            "all": {"cbr": 1.0, "precision": 1.0, "f1": 1.0, "decision_accuracy": 1.0, "evidence_coverage": 1.0, "critical_evidence_coverage": 1.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 1.0, "total_runtime_ms": 1200, "total_cost": 0.02},
        },
    }

    md = generate_markdown_report(run2, compare_results=run1)
    assert "# ReleaseGuard Evaluation Report: `final_run`" in md
    assert "Comparison with `baseline_run`" in md
    assert "Critical Blocker Recall (primary)" in md

    # Test report CLI with --out
    r1_file = tmp_path / "run1.json"
    r2_file = tmp_path / "run2.json"
    out_md = tmp_path / "report.md"
    r1_file.write_text(json.dumps(run1), encoding="utf-8")
    r2_file.write_text(json.dumps(run2), encoding="utf-8")

    code = report_main([str(r2_file), "--compare", str(r1_file), "--out", str(out_md)])
    assert code == 0
    assert out_md.exists()
    assert "Comparison with `baseline_run`" in out_md.read_text(encoding="utf-8")


def test_eval_report_cli_missing_file_returns_one() -> None:
    code = report_main(["non_existent_results.json"])
    assert code == 1


def test_eval_run_cli_main(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    case_run_dir = runs_dir / "run_case_01"
    case_run_dir.mkdir(parents=True, exist_ok=True)
    report = create_mock_report("case_01", decision=Decision.GO)
    (case_run_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json")), encoding="utf-8"
    )

    code = run_main(
        [
            "--mode",
            "baseline",
            "--cases",
            "case_01",
            "--dry-run",
            "--results-dir",
            str(results_dir),
            "--runs-dir",
            str(runs_dir),
        ]
    )
    assert code == 0
