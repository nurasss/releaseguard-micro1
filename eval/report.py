# path: eval/report.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


METRIC_LABELS = [
    ("cbr", "Critical Blocker Recall (primary)", "{:.2%}"),
    ("high_blocker_recall", "High Blocker Recall", "{:.2%}"),
    ("precision", "Precision", "{:.2%}"),
    ("f1", "F1 Score", "{:.4f}"),
    ("decision_accuracy", "Decision Accuracy", "{:.2%}"),
    ("evidence_coverage", "Evidence Coverage", "{:.2%}"),
    ("critical_evidence_coverage", "Critical Evidence Coverage", "{:.2%}"),
    ("unsupported_critical_total", "Unsupported Critical Findings", "{:d}"),
    ("trap_hits_total", "Trap Hits Total", "{:d}"),
    ("successful_run_rate", "Successful Run Rate", "{:.2%}"),
    ("total_runtime_ms", "Total Runtime", "{:.1f}s"),
    ("total_cost", "Total Estimated Cost", "${:.4f}"),
]


def format_value(key: str, val: Any) -> str:
    if val is None:
        return "N/A"
    if key in ("cbr", "high_blocker_recall", "precision", "decision_accuracy", "evidence_coverage", "critical_evidence_coverage", "successful_run_rate"):
        return f"{val * 100:.1f}%"
    elif key == "f1":
        return f"{val:.4f}"
    elif key in ("unsupported_critical_total", "trap_hits_total"):
        return f"{int(val)}"
    elif key == "total_runtime_ms":
        return f"{val / 1000.0:.1f}s"
    elif key == "total_cost":
        return f"${val:.4f}"
    return str(val)


def generate_markdown_report(results: dict[str, Any], compare_results: dict[str, Any] | None = None) -> str:
    meta = results.get("meta", {})
    per_case = results.get("per_case", [])
    aggregate = results.get("aggregate", {})

    lines: list[str] = []
    lines.append(f"# ReleaseGuard Evaluation Report: `{meta.get('run_label', 'Unknown')}`\n")
    lines.append(f"- **Mode:** `{meta.get('mode', 'unknown')}`")
    lines.append(f"- **Model ID:** `{meta.get('model_id', 'unknown')}`")
    lines.append(f"- **Prompt Version:** `{meta.get('prompt_version', 'unknown')}`")
    lines.append(f"- **Generated at:** `{meta.get('generated_at_utc', 'unknown')}`")
    lines.append(f"- **Cases Total:** `{meta.get('cases_total', len(per_case))}`\n")

    # 1. Per-Case Table
    lines.append("## Per-Case Results\n")
    lines.append("| Case | Expected | Actual | Decision Match | Matched / Total Blockers | False Positives | Trap Hits | Evidence Cov | Runtime | Cost | Status |")
    lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|:---:|")

    for case in per_case:
        c_id = case.get("case_id", "")
        dec_exp = case.get("decision_expected", "")
        dec_act = case.get("decision_actual", "")
        match_symbol = "✅" if (dec_exp == dec_act and case.get("status") == "success") else "❌"
        matched = len(case.get("matched_blockers", []))
        # `blockers_total` is the critical-only denominator used by the primary
        # CBR metric. The display table should show all critical and high gold
        # blockers, including REVIEW cases such as stale artifacts or missing
        # tests.
        total_b = len(case.get("matched_blockers", [])) + len(case.get("missed_blockers", []))
        fps = len(case.get("false_positives", []))
        traps = case.get("trap_hits", 0)
        ev_cov = f"{case.get('evidence_coverage', 0.0) * 100:.0f}%"
        runtime_s = f"{case.get('runtime_ms', 0) / 1000.0:.1f}s"
        cost = f"${case.get('estimated_cost', 0.0):.4f}"
        status = "OK" if case.get("status") == "success" else "**FAILED**"

        lines.append(
            f"| `{c_id}` | `{dec_exp}` | `{dec_act}` | {match_symbol} | {matched}/{total_b} | {fps} | {traps} | {ev_cov} | {runtime_s} | {cost} | {status} |"
        )

    # 2. Aggregate Metrics Table
    lines.append("\n## Aggregate Metrics\n")
    lines.append("| Metric | Development (Cases 01--08) | Held-Out (Cases 09--12) | All Cases |")
    lines.append("|---|:---:|:---:|:---:|")

    dev_agg = aggregate.get("development", {})
    held_agg = aggregate.get("held_out", {})
    all_agg = aggregate.get("all", {})

    for key, name, _ in METRIC_LABELS:
        v_dev = format_value(key, dev_agg.get(key))
        v_held = format_value(key, held_agg.get(key))
        v_all = format_value(key, all_agg.get(key))
        lines.append(f"| **{name}** | {v_dev} | {v_held} | {v_all} |")

    # 3. Comparison Mode
    if compare_results is not None:
        comp_meta = compare_results.get("meta", {})
        comp_agg = compare_results.get("aggregate", {})
        lines.append(f"\n## Comparison with `{comp_meta.get('run_label', 'Baseline')}`\n")
        lines.append(f"Comparing `{meta.get('run_label')}` (Current) vs `{comp_meta.get('run_label')}` (Reference):\n")
        lines.append("| Metric | Reference (All) | Current (All) | Delta (All) | Reference (Held-Out) | Current (Held-Out) | Delta (Held-Out) |")
        lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|")

        comp_all = comp_agg.get("all", {})
        comp_held = comp_agg.get("held_out", {})

        for key, name, _ in METRIC_LABELS:
            c_all_val = comp_all.get(key, 0.0)
            cur_all_val = all_agg.get(key, 0.0)
            c_held_val = comp_held.get(key, 0.0)
            cur_held_val = held_agg.get(key, 0.0)

            delta_all = (cur_all_val - c_all_val) if isinstance(cur_all_val, (int, float)) and isinstance(c_all_val, (int, float)) else 0.0
            delta_held = (cur_held_val - c_held_val) if isinstance(cur_held_val, (int, float)) and isinstance(c_held_val, (int, float)) else 0.0

            if key in ("cbr", "high_blocker_recall", "precision", "decision_accuracy", "evidence_coverage", "critical_evidence_coverage", "successful_run_rate"):
                d_all_str = f"{delta_all * 100:+.1f}%"
                d_held_str = f"{delta_held * 100:+.1f}%"
            elif key == "f1":
                d_all_str = f"{delta_all:+.4f}"
                d_held_str = f"{delta_held:+.4f}"
            elif key in ("unsupported_critical_total", "trap_hits_total"):
                d_all_str = f"{int(delta_all):+d}"
                d_held_str = f"{int(delta_held):+d}"
            elif key == "total_runtime_ms":
                d_all_str = f"{delta_all / 1000.0:+.1f}s"
                d_held_str = f"{delta_held / 1000.0:+.1f}s"
            else:
                d_all_str = f"{delta_all:+.4f}"
                d_held_str = f"{delta_held:+.4f}"

            lines.append(
                f"| **{name}** | {format_value(key, c_all_val)} | {format_value(key, cur_all_val)} | **{d_all_str}** | {format_value(key, c_held_val)} | {format_value(key, cur_held_val)} | **{d_held_str}** |"
            )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate human-readable Markdown evaluation report.")
    parser.add_argument("results_file", help="Path to results.json to report")
    parser.add_argument("--compare", default=None, help="Path to reference results.json for side-by-side delta comparison")
    parser.add_argument("--out", default=None, help="Optional output file path to write Markdown")

    args = parser.parse_args(argv)

    results_path = Path(args.results_file)
    if not results_path.exists():
        print(f"Error: results file not found: {results_path}", file=sys.stderr)
        return 1

    with results_path.open(encoding="utf-8") as f:
        results_data = json.load(f)

    compare_data = None
    if args.compare:
        comp_path = Path(args.compare)
        if not comp_path.exists():
            print(f"Error: compare file not found: {comp_path}", file=sys.stderr)
            return 1
        with comp_path.open(encoding="utf-8") as f:
            compare_data = json.load(f)

    report_md = generate_markdown_report(results_data, compare_data)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        print(f"Report written to {out_path}")
    else:
        print(report_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
