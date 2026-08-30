"""Collect the reproducible, redacted artifacts intended for submission."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# When invoked as ``python scripts/prepare_submission.py``, Python puts the
# scripts directory on sys.path rather than the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.report import generate_markdown_report
from eval.run import _make_comparison
from scripts.check_quality_gates import evaluate_gates


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_result(results_dir: Path, mode: str, ablation: str = "none") -> Path:
    candidates: list[tuple[float, Path]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            meta = _load(path).get("meta", {})
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("mode") == mode and meta.get("ablation", "none") == ablation:
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        raise FileNotFoundError(f"No {mode}/{ablation} results found in {results_dir}")
    return max(candidates, key=lambda item: item[0])[1]


def _latest_live_result(results_dir: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            meta = _load(path).get("meta", {})
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("execution_mode") == "live_provider" or (
            meta.get("mode") in {"baseline", "final"}
            and meta.get("model_id") == "gemini-2.5-flash"
            and meta.get("ablation", "none") == "none"
        ):
            candidates.append((path.stat().st_mtime, path))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _copy_result_tree(result_file: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    source_dir = result_file.parent
    for source in source_dir.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_dir)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _find_case12_run(runs_dir: Path) -> tuple[dict[str, Any], Path]:
    candidates: list[tuple[str, dict[str, Any], Path]] = []
    for report_path in runs_dir.glob("*/report.json"):
        try:
            report = _load(report_path)
            run_path = report_path.parent / "run.json"
            run = _load(run_path) if run_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            continue
        if (
            report.get("repository_url", "").rstrip("/").endswith("/case_12")
            and report.get("mode") == "final"
            and run.get("status", "completed") == "completed"
        ):
            candidates.append((run.get("finished_at", ""), report, report_path.parent))
    if not candidates:
        raise FileNotFoundError(f"No completed final case_12 run found in {runs_dir}")
    _, report, run_dir = max(candidates, key=lambda item: item[0])
    trajectory = run_dir.parent.parent / "trajectories" / f"{report['audit_run_id']}.jsonl"
    # The usual layout is <project>/runs/<audit_id>; derive the project root
    # from the caller's runs_dir when the default path is used.
    return report, trajectory


def _split_trajectory(trajectory: Path, output_dir: Path) -> tuple[int, int]:
    if not trajectory.exists():
        raise FileNotFoundError(f"Trajectory not found: {trajectory}")
    analyzer_lines: list[str] = []
    verifier_lines: list[str] = []
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        step = json.loads(line)
        component = step.get("component")
        encoded = json.dumps(step, ensure_ascii=False, separators=(",", ":"))
        if component == "analyzer":
            analyzer_lines.append(encoded)
        elif component == "verifier":
            verifier_lines.append(encoded)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "analyzer_case_12.jsonl").write_text(
        "\n".join(analyzer_lines) + ("\n" if analyzer_lines else ""), encoding="utf-8"
    )
    (output_dir / "verifier_case_12.jsonl").write_text(
        "\n".join(verifier_lines) + ("\n" if verifier_lines else ""), encoding="utf-8"
    )
    return len(analyzer_lines), len(verifier_lines)


def prepare_submission(
    source_root: Path,
    results_dir: Path,
    runs_dir: Path,
    trajectories_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    results_dir = results_dir.resolve()
    runs_dir = runs_dir.resolve()
    trajectories_dir = trajectories_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_file = _latest_result(results_dir, "baseline")
    final_file = _latest_result(results_dir, "final")
    baseline = _load(baseline_file)
    final = _load(final_file)

    _copy_result_tree(baseline_file, output_dir / "results" / "baseline")
    _copy_result_tree(final_file, output_dir / "results" / "final")

    live_result = _latest_live_result(results_dir)
    if live_result is not None:
        live_out = output_dir / "results" / "live_provider_attempt"
        live_out.mkdir(parents=True, exist_ok=True)
        # Keep the machine-readable failed attempt, but do not copy its large
        # raw per-case reports into the curated submission.
        shutil.copy2(live_result, live_out / "results.json")
        (live_out / "README.md").write_text(
            "# Live provider attempt\n\n"
            "This excluded-from-gates attempt used the configured Gemini provider and "
            "was interrupted by provider quota/rate-limit errors. It is retained as "
            "an honest record and is not compared with the deterministic offline run.\n",
            encoding="utf-8",
        )

    ablation_names = ("no_verifier", "no_evidence_enforcement", "no_deterministic_checks", "it5_subagents")
    ablation_summary: dict[str, Any] = {
        "schema_version": "1.0",
        "reference_final": final.get("meta", {}),
        "ablations": {},
    }
    for ablation in ablation_names:
        try:
            ablation_file = _latest_result(results_dir, "final", ablation)
        except FileNotFoundError:
            continue
        _copy_result_tree(ablation_file, output_dir / "results" / "ablations" / ablation)
        ablation_payload = _load(ablation_file)
        ablation_summary["ablations"][ablation] = {
            "meta": ablation_payload.get("meta", {}),
            "aggregate_all": ablation_payload.get("aggregate", {}).get("all", {}),
        }

    (output_dir / "results" / "ablations" / "comparison.json").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "results" / "ablations" / "comparison.json").write_text(
        json.dumps(ablation_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    ablation_lines = [
        "# Ablation comparison",
        "",
        "All rows use the same frozen 12 cases and the same offline fixture model.",
        "",
        "| Run | CBR | Precision | Critical evidence | Unsupported critical | Successful run rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    reference_metrics = final.get("aggregate", {}).get("all", {})
    rows = [("final (Verifier ON)", reference_metrics)]
    rows.extend(
        (name, data["aggregate_all"])
        for name, data in ablation_summary["ablations"].items()
    )
    for name, metrics in rows:
        ablation_lines.append(
            f"| `{name}` | {metrics.get('cbr', 0.0):.4f} | {metrics.get('precision', 0.0):.4f} | "
            f"{metrics.get('critical_evidence_coverage', 0.0):.4f} | "
            f"{metrics.get('unsupported_critical_total', 0)} | "
            f"{metrics.get('successful_run_rate', 0.0):.4f} |"
        )
    (output_dir / "results" / "ablations" / "comparison.md").write_text(
        "\n".join(ablation_lines) + "\n", encoding="utf-8"
    )

    comparison = _make_comparison(final, baseline, Path("results/baseline/results.json"))
    (output_dir / "results" / "comparison.json").parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "results" / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "results" / "comparison.md").write_text(
        generate_markdown_report(final, compare_results=baseline) + "\n", encoding="utf-8"
    )
    gate_report = evaluate_gates(baseline, final)
    gate_report["baseline_file"] = "results/baseline/results.json"
    gate_report["final_file"] = "results/final/results.json"
    (output_dir / "results" / "quality_gates.json").write_text(
        json.dumps(gate_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # Replace any harness-local comparison files copied from the final run
    # directory with portable curated versions.
    (output_dir / "results" / "final" / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "results" / "final" / "comparison.md").write_text(
        generate_markdown_report(final, compare_results=baseline) + "\n", encoding="utf-8"
    )

    case12_report, _ = _find_case12_run(runs_dir)
    case12_id = case12_report["audit_run_id"]
    case12_run_dir = runs_dir / case12_id
    case12_out = output_dir / "case_12"
    case12_out.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "report.md", "run.json", "snapshot.json"):
        candidate = case12_run_dir / name
        if candidate.exists():
            shutil.copy2(candidate, case12_out / name)

    trajectory = trajectories_dir / f"{case12_id}.jsonl"
    analyzer_count, verifier_count = _split_trajectory(trajectory, output_dir / "trajectories")
    (output_dir / "trajectories" / "README.md").write_text(
        "# Representative trajectories\n\n"
        "These JSONL files are projections of one final `case_12` run. They contain\n"
        "redacted inputs, bounded summaries, tool names, and evidence IDs only.\n\n"
        f"- Analyzer steps: {analyzer_count}\n"
        f"- Verifier steps: {verifier_count}\n",
        encoding="utf-8",
    )

    it5_dir = output_dir / "removed_experiment"
    it5_dir.mkdir(parents=True, exist_ok=True)
    it5_result = output_dir / "results" / "ablations" / "it5_subagents" / "results.json"
    it5_metrics = _load(it5_result).get("aggregate", {}).get("all", {}) if it5_result.exists() else {}
    (it5_dir / "README.md").write_text(
        "# Removed experiment: It5 specialized subagents\n\n"
        "This is the executed comparison requested by the changelog. It runs CI,\n"
        "security, and test specialists and combines their bounded outputs before\n"
        "the same verifier and decision policy. The measured result is stored under\n"
        "`results/ablations/it5_subagents/`.\n\n"
        f"All-case CBR: {it5_metrics.get('cbr', 'N/A')}\n"
        f"All-case precision: {it5_metrics.get('precision', 'N/A')}\n"
        f"All-case successful run rate: {it5_metrics.get('successful_run_rate', 'N/A')}\n",
        encoding="utf-8",
    )

    video_path = output_dir / "video" / "releaseguard_demo.mp4"
    if not video_path.exists():
        video_script = source_root / "scripts" / "create_submission_video.py"
        if video_script.exists():
            video_result = subprocess.run(
                [sys.executable, str(video_script), "--source-root", str(source_root), "--out", str(video_path)],
                cwd=source_root,
                check=False,
            )
            if video_result.returncode != 0:
                raise RuntimeError("submission video could not be generated")
    if not video_path.exists():
        raise FileNotFoundError(f"Required submission video not found: {video_path}")
    (output_dir / "video" / "README.md").write_text(
        "# Submission video\n\n"
        "`releaseguard_demo.mp4` is a short, silent 20-second AVFoundation-rendered demo. "
        "It covers the security boundary, frozen 12-case result, case 12 trajectory, "
        "and packaged artifacts.\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "# ReleaseGuard submission bundle\n\n"
        "This directory is a curated, redacted selection for review. It contains\n"
        "the 12-case baseline/final results and comparison, ablations, representative\n"
        "Analyzer and Verifier trajectories, the case 12 report, the executed removed\n"
        "experiment, quality-gate output, and a short demo video. Local runtime\n"
        "directories and secrets are excluded by the ZIP packager.\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "1.0",
        "source": "local redacted artifacts selected by scripts/prepare_submission.py",
        "baseline_result": baseline.get("meta", {}),
        "final_result": final.get("meta", {}),
        "case_12_run_id": case12_id,
        "required_artifacts": [
            "results/baseline/results.json",
            "results/final/results.json",
            "results/comparison.json",
            "results/comparison.md",
            "results/quality_gates.json",
            "results/ablations/comparison.json",
            "trajectories/analyzer_case_12.jsonl",
            "trajectories/verifier_case_12.jsonl",
            "case_12/report.json",
            "removed_experiment/README.md",
            "video/releaseguard_demo.mp4",
        ],
    }
    if live_result is not None:
        manifest["live_provider_attempt"] = "results/live_provider_attempt/results.json"
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare curated ReleaseGuard submission artifacts")
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--results-dir", default="eval/results")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--trajectories-dir", default="trajectories")
    parser.add_argument("--out-dir", default="submission")
    args = parser.parse_args(argv)

    try:
        manifest = prepare_submission(
            source_root=Path(args.source_root),
            results_dir=Path(args.results_dir),
            runs_dir=Path(args.runs_dir),
            trajectories_dir=Path(args.trajectories_dir),
            output_dir=Path(args.out_dir),
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"Submission preparation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared {len(manifest['required_artifacts'])} required artifact paths under {Path(args.out_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
