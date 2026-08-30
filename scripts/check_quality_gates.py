"""Evaluate the frozen submission quality gates from baseline/final results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _find_latest(results_dir: Path, mode: str) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue
        meta = payload.get("meta", {})
        if meta.get("mode") != mode or meta.get("ablation", "none") != "none":
            continue
        candidates.append((path.stat().st_mtime, path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def evaluate_gates(baseline: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    before = baseline.get("aggregate", {}).get("all", {})
    after = final.get("aggregate", {}).get("all", {})

    checks = {
        "cbr_minimum": {
            "actual": after.get("cbr", 0.0),
            "threshold": 0.85,
            "operator": ">=",
            "passed": after.get("cbr", 0.0) >= 0.85,
        },
        "cbr_improvement_over_baseline": {
            "actual": after.get("cbr", 0.0) - before.get("cbr", 0.0),
            "threshold": 0.20,
            "operator": ">=",
            "passed": after.get("cbr", 0.0) - before.get("cbr", 0.0) >= 0.20,
        },
        "critical_evidence_coverage": {
            "actual": after.get("critical_evidence_coverage", 0.0),
            "threshold": 1.0,
            "operator": "=",
            "passed": after.get("critical_evidence_coverage", 0.0) >= 1.0,
        },
        "unsupported_critical_findings": {
            "actual": after.get("unsupported_critical_total", 0),
            "threshold": 0,
            "operator": "=",
            "passed": after.get("unsupported_critical_total", 0) == 0,
        },
        "successful_run_rate": {
            "actual": after.get("successful_run_rate", 0.0),
            "threshold": 0.95,
            "operator": ">=",
            "passed": after.get("successful_run_rate", 0.0) >= 0.95,
        },
    }
    return {
        "schema_version": "1.0",
        "passed": all(item["passed"] for item in checks.values()),
        "baseline": baseline.get("meta", {}),
        "final": final.get("meta", {}),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check ReleaseGuard submission quality gates")
    parser.add_argument("--results-dir", default="eval/results")
    parser.add_argument("--baseline", default=None, help="Explicit baseline results.json")
    parser.add_argument("--final", dest="final_results", default=None, help="Explicit final results.json")
    parser.add_argument("--out", default="submission/results/quality_gates.json")
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    baseline_path = Path(args.baseline) if args.baseline else _find_latest(results_dir, "baseline")
    final_path = Path(args.final_results) if args.final_results else _find_latest(results_dir, "final")
    if baseline_path is None or final_path is None:
        missing = []
        if baseline_path is None:
            missing.append("baseline")
        if final_path is None:
            missing.append("final")
        print(f"Quality gates cannot run: missing {', '.join(missing)} results", file=sys.stderr)
        return 1

    try:
        baseline = _load(baseline_path)
        final = _load(final_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Quality gates cannot read results: {exc}", file=sys.stderr)
        return 1

    report = evaluate_gates(baseline, final)
    output = Path(args.out)
    if output.parent.name == "results" and output.parent.parent.name == "submission":
        report["baseline_file"] = "results/baseline/results.json"
        report["final_file"] = "results/final/results.json"
    else:
        report["baseline_file"] = str(baseline_path)
        report["final_file"] = str(final_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for name, check in report["checks"].items():
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{status} {name}: {check['actual']} {check['operator']} {check['threshold']}")
    print(f"Quality gates: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"Gate report: {output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
