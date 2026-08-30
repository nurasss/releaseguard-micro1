# path: eval/run.py
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.orchestration.runner import AuditRunner
from app.schemas.enums import RunStatus
from app.schemas.report import AuditReport
from eval.score import CaseScore, aggregate, score_case
from eval.validate_gold import load_gold


DEFAULT_CASES = [f"case_{i:02d}" for i in range(1, 13)]


def _latest_results_file(results_root: Path, mode: str, exclude: Path | None = None) -> Path | None:
    """Find the newest completed results file for a reference mode."""
    candidates: list[tuple[float, Path]] = []
    for path in results_root.glob("*/results.json"):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("meta", {}).get("mode") != mode:
            continue
        candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _make_comparison(current: dict[str, Any], baseline: dict[str, Any], baseline_path: Path) -> dict[str, Any]:
    """Create a machine-readable baseline/final comparison artifact."""
    metrics = (
        "cbr",
        "high_blocker_recall",
        "precision",
        "f1",
        "decision_accuracy",
        "evidence_coverage",
        "critical_evidence_coverage",
        "unsupported_critical_total",
        "trap_hits_total",
        "successful_run_rate",
        "total_runtime_ms",
        "total_cost",
    )
    deltas: dict[str, dict[str, float | int]] = {}
    for split in ("development", "held_out", "all"):
        before = baseline.get("aggregate", {}).get(split, {})
        after = current.get("aggregate", {}).get(split, {})
        deltas[split] = {
            metric: after.get(metric, 0) - before.get(metric, 0)
            for metric in metrics
        }
    return {
        "schema_version": "1.0",
        "baseline": {
            "run_label": baseline.get("meta", {}).get("run_label", ""),
            "mode": baseline.get("meta", {}).get("mode", "baseline"),
            "results_file": str(baseline_path),
        },
        "final": {
            "run_label": current.get("meta", {}).get("run_label", ""),
            "mode": current.get("meta", {}).get("mode", "final"),
        },
        "deltas": deltas,
    }


def _write_final_comparison(
    results_root: Path,
    out_run_dir: Path,
    current: dict[str, Any],
) -> Path | None:
    """Attach comparison.json and comparison.md to a normal final run."""
    baseline_path = _latest_results_file(results_root, "baseline", exclude=out_run_dir / "results.json")
    if baseline_path is None:
        return None
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    comparison = _make_comparison(current, baseline, baseline_path)
    comparison_path = out_run_dir / "comparison.json"
    comparison_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    from eval.report import generate_markdown_report

    (out_run_dir / "comparison.md").write_text(
        generate_markdown_report(current, compare_results=baseline) + "\n",
        encoding="utf-8",
    )
    return comparison_path


def run_evaluation(
    mode: str,
    case_ids: list[str] | None = None,
    label: str | None = None,
    resume: bool = False,
    dry_run: bool = False,
    cases_dir: Path | str = "eval/cases",
    gold_dir: Path | str = "eval/gold",
    results_dir: Path | str = "eval/results",
    runs_dir: Path | str = "runs",
    db_path: Path | str | None = None,
    runner: AuditRunner | None = None,
    ablation: str = "none",
) -> tuple[dict[str, Any], int]:
    """Execute evaluation harness over specified cases and compute machine-readable results.json.

    Returns (results_dict, exit_code).
    """
    cases_dir_path = Path(cases_dir).resolve()
    gold_dir_path = Path(gold_dir).resolve()
    results_dir_path = Path(results_dir).resolve()
    runs_dir_path = Path(runs_dir).resolve()

    selected_case_ids = case_ids or DEFAULT_CASES
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y_%m_%d_%H%M%S")
    ablation_suffix = f"_{ablation}" if ablation != "none" else ""
    run_label = label or f"{mode}{ablation_suffix}_{timestamp_str}"

    out_run_dir = results_dir_path / run_label
    raw_dir = out_run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    if db_path:
        settings.db_path = Path(db_path).resolve()
    settings.data_dir = runs_dir_path
    reported_model_id = settings.offline_model_id if settings.offline_mode else settings.model_id

    if runner is None and not dry_run:
        runner = AuditRunner(settings=settings)

    scores: list[CaseScore] = []
    has_failures = False

    print(f"=== ReleaseGuard Evaluation Harness ===", flush=True)
    print(f"Label:       {run_label}", flush=True)
    print(f"Mode:        {mode}", flush=True)
    print(f"Cases ({len(selected_case_ids)}): {', '.join(selected_case_ids)}", flush=True)
    print(f"Dry-run:     {dry_run}", flush=True)
    print(f"Resume:      {resume}", flush=True)
    print(f"Output:      {out_run_dir}\n", flush=True)

    for idx, case_id in enumerate(selected_case_ids, 1):
        gold_file = gold_dir_path / f"{case_id}.json"
        if not gold_file.exists():
            print(f"[{idx}/{len(selected_case_ids)}] {case_id}: ERROR - gold file missing: {gold_file}", flush=True)
            has_failures = True
            continue

        gold_data = load_gold(gold_file)
        case_path = cases_dir_path / case_id
        raw_case_file = raw_dir / f"{case_id}.json"

        report: AuditReport | None = None
        run_status = "completed"

        # 1. Resume check
        if resume and raw_case_file.exists():
            try:
                with raw_case_file.open(encoding="utf-8") as f:
                    raw_payload = json.load(f)
                report = AuditReport.model_validate(raw_payload)
                print(f"[{idx}/{len(selected_case_ids)}] {case_id}: resumed from {raw_case_file.name}", flush=True)
            except Exception as e:
                print(f"[{idx}/{len(selected_case_ids)}] {case_id}: resume failed to load {raw_case_file.name}: {e}", flush=True)

        # 2. Dry-run lookup
        if report is None and dry_run:
            # Find every report.json belonging to this exact case_id (identified by the
            # last path segment of repository_url, e.g. ".../eval/case_03" -> "case_03").
            # Matching on requested_ref is NOT safe: distinct cases can share the same ref
            # (e.g. case_03 and case_10 are both "v3.0.0"), which would attribute one
            # case's report to another.
            best_candidate: tuple[str, dict[str, Any], dict[str, Any] | None] | None = None
            best_timestamp = ""
            for candidate in runs_dir_path.glob("*/report.json"):
                try:
                    with candidate.open(encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                repo_url = data.get("repository_url", "")
                candidate_case_id = repo_url.rstrip("/").rsplit("/", 1)[-1]
                if candidate_case_id != case_id:
                    continue

                run_json_path = candidate.parent / "run.json"
                run_data: dict[str, Any] | None = None
                if run_json_path.exists():
                    try:
                        with run_json_path.open(encoding="utf-8") as f:
                            run_data = json.load(f)
                    except Exception:
                        run_data = None

                timestamp = (run_data or {}).get("finished_at") or (run_data or {}).get("started_at") or ""
                if best_candidate is None or timestamp > best_timestamp:
                    best_candidate = (str(candidate), data, run_data)
                    best_timestamp = timestamp

            found = False
            if best_candidate is not None:
                _, data, run_data = best_candidate
                try:
                    report = AuditReport.model_validate(data)
                    found = True
                    if run_data is not None:
                        run_status = run_data.get("status", "completed")
                except Exception:
                    pass

            if not found and raw_case_file.exists():
                try:
                    with raw_case_file.open(encoding="utf-8") as f:
                        report = AuditReport.model_validate(json.load(f))
                    found = True
                except Exception:
                    pass

            if not found:
                print(f"[{idx}/{len(selected_case_ids)}] {case_id}: dry-run found no prior report, marking failed", flush=True)
                run_status = "failed"
            elif run_status == "failed":
                print(f"[{idx}/{len(selected_case_ids)}] {case_id}: dry-run matched report with run status=failed", flush=True)

        # 3. Live audit run
        if report is None and not dry_run:
            print(f"[{idx}/{len(selected_case_ids)}] {case_id} ({gold_data.get('name', '')})... ", end="", flush=True)
            t0 = time.perf_counter()
            try:
                assert runner is not None
                outcome = runner.run_case(case_dir=case_path, mode=mode, ablation=ablation)
                report = outcome.report
                if outcome.run.status == RunStatus.failed:
                    run_status = "failed"
                    has_failures = True
            except Exception as exc:
                print(f"FAILED with exception: {exc}", flush=True)
                run_status = "failed"
                has_failures = True

            elapsed = time.perf_counter() - t0
            if run_status != "failed" and report:
                print(f"{report.decision.value} (expected {gold_data.get('expected_decision')}) [{elapsed:.1f}s]", flush=True)

        # 4. Save raw copy if report is available
        if report is not None:
            with raw_case_file.open("w", encoding="utf-8") as f:
                json.dump(report.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

        # 5. Score case
        score = score_case(report, gold_data, run_status=run_status)
        scores.append(score)

        if score.status == "failed":
            has_failures = True

    # 6. Aggregate metrics
    agg = aggregate(scores)

    # 7. Assemble results.json structure according to Section 11 of EVALUATION_SPEC.md
    results_payload = {
        "meta": {
            "run_label": run_label,
            "generated_at_utc": now_utc.isoformat().replace("+00:00", "Z"),
            "mode": mode,
            "ablation": ablation,
            "model_id": reported_model_id,
            "execution_mode": "offline_fixture" if settings.offline_mode else "live_provider",
            "provider": "local-deterministic-fixture" if settings.offline_mode else settings.llm_provider,
            "prompt_version": (
                "offline-b1-v1" if settings.offline_mode and mode == "baseline" else
                "offline-final-v1" if settings.offline_mode else
                "b1-v1" if mode == "baseline" else "final-v1"
            ),
            "system_version": "releaseguard-v1",
            "spec_version": "1.0",
            "frozen_at": "2026-08-29",
            "cases_total": len(selected_case_ids),
            "timeout_s": settings.audit_deadline_s,
        },
        "per_case": [s.model_dump() for s in scores],
        "aggregate": agg,
    }

    results_file = out_run_dir / "results.json"
    with results_file.open("w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2, ensure_ascii=False)

    comparison_path = None
    if mode == "final" and ablation == "none":
        comparison_path = _write_final_comparison(results_dir_path, out_run_dir, results_payload)

    print(f"\nResults saved to: {results_file}", flush=True)
    if comparison_path is not None:
        print(f"Comparison saved to: {comparison_path}", flush=True)
    exit_code = 1 if has_failures else 0
    return results_payload, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReleaseGuard Evaluation Harness Runner")
    parser.add_argument("--mode", required=True, choices=["baseline", "final"], help="Audit mode to evaluate")
    parser.add_argument("--cases", default=None, help="Comma-separated case IDs (e.g. case_01,case_02)")
    parser.add_argument("--label", default=None, help="Run label (default: <mode>_<timestamp>)")
    parser.add_argument("--resume", action="store_true", help="Resume prior run if raw reports exist")
    parser.add_argument("--dry-run", action="store_true", help="Score existing reports without running LLM")
    parser.add_argument("--cases-dir", default="eval/cases", help="Path to cases directory")
    parser.add_argument("--gold-dir", default="eval/gold", help="Path to gold directory")
    parser.add_argument("--results-dir", default="eval/results", help="Base output directory for results")
    parser.add_argument("--runs-dir", default="runs", help="Base directory where runs are stored")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument(
        "--ablation",
        default="none",
        choices=[
            "none",
            "no_verifier",
            "no_evidence_enforcement",
            "no_deterministic_checks",
            "no_tool_output_normalization",
            "it5_subagents",
        ],
        help="Ablation to apply in 'final' mode (ignored in 'baseline' mode). Default: none.",
    )

    args = parser.parse_args(argv)
    case_ids = [c.strip() for c in args.cases.split(",")] if args.cases else None

    _, exit_code = run_evaluation(
        mode=args.mode,
        case_ids=case_ids,
        label=args.label,
        resume=args.resume,
        dry_run=args.dry_run,
        cases_dir=args.cases_dir,
        gold_dir=args.gold_dir,
        results_dir=args.results_dir,
        runs_dir=args.runs_dir,
        db_path=args.db,
        ablation=args.ablation,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
