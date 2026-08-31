"""Collect the reproducible, redacted artifacts intended for submission."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# When invoked as ``.venv/bin/python scripts/prepare_submission.py``, Python puts the
# scripts directory on sys.path rather than the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.report import generate_markdown_report
from eval.run import _make_comparison
from scripts.check_quality_gates import evaluate_gates


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_result(
    results_dir: Path,
    mode: str,
    ablation: str = "none",
    execution_mode: str | None = None,
) -> Path:
    candidates: list[tuple[float, Path]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            meta = _load(path).get("meta", {})
        except (OSError, json.JSONDecodeError):
            continue
        if (
            meta.get("mode") == mode
            and meta.get("ablation", "none") == ablation
            and (execution_mode is None or meta.get("execution_mode") == execution_mode)
        ):
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


def _latest_successful_live_pair(results_dir: Path) -> tuple[Path, Path] | None:
    runs: list[tuple[float, Path, dict[str, Any], dict[str, Any]]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue
        meta = payload.get("meta", {})
        aggregate = payload.get("aggregate", {}).get("all", {})
        if (
            meta.get("execution_mode") == "live_provider"
            and meta.get("ablation", "none") == "none"
            and meta.get("cases_total") == 12
            and aggregate.get("successful_run_rate", 0.0) >= 0.95
        ):
            runs.append((path.stat().st_mtime, path, meta, payload))

    finals = sorted(
        (item for item in runs if item[2].get("mode") == "final"),
        key=lambda item: item[0],
        reverse=True,
    )
    baselines = [item for item in runs if item[2].get("mode") == "baseline"]
    for _, final_path, final_meta, _ in finals:
        matching = [
            item
            for item in baselines
            if item[2].get("provider") == final_meta.get("provider")
            and item[2].get("model_id") == final_meta.get("model_id")
        ]
        if matching:
            baseline_path = max(matching, key=lambda item: item[0])[1]
            return baseline_path, final_path
    return None


def _latest_failed_live_result(results_dir: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for path in results_dir.glob("*/results.json"):
        try:
            payload = _load(path)
        except (OSError, json.JSONDecodeError):
            continue
        meta = payload.get("meta", {})
        success_rate = payload.get("aggregate", {}).get("all", {}).get("successful_run_rate", 0.0)
        if meta.get("execution_mode") == "live_provider" and success_rate < 0.95:
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
            and run.get("ablation", "none") == "none"
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

    baseline_file = _latest_result(results_dir, "baseline", execution_mode="offline_fixture")
    final_file = _latest_result(results_dir, "final", execution_mode="offline_fixture")
    baseline = _load(baseline_file)
    final = _load(final_file)

    _copy_result_tree(baseline_file, output_dir / "results" / "baseline")
    _copy_result_tree(final_file, output_dir / "results" / "final")

    live_pair = _latest_successful_live_pair(results_dir)
    failed_live_result = _latest_failed_live_result(results_dir)
    if failed_live_result is not None:
        live_out = output_dir / "results" / "live_provider_attempt"
        live_out.mkdir(parents=True, exist_ok=True)
        # Keep the machine-readable failed attempt, but do not copy its large
        # raw per-case reports into the curated submission.
        live_payload = _load(failed_live_result)
        live_payload.setdefault("meta", {}).setdefault("execution_mode", "live_provider")
        live_payload.setdefault("meta", {}).setdefault("provider", "unknown")
        attempt_provider = live_payload["meta"].get("provider", "unknown")
        attempt_model = live_payload["meta"].get("model_id", "unknown")
        (live_out / "results.json").write_text(
            json.dumps(live_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (live_out / "README.md").write_text(
            "# Live provider attempt\n\n"
            f"This excluded-from-gates attempt used provider `{attempt_provider}` with "
            f"model `{attempt_model}` and "
            "did not produce a successful 12-case baseline/final pair. It is retained as an honest "
            "record and is not compared with the deterministic offline run.\n",
            encoding="utf-8",
        )

    live_baseline: dict[str, Any] | None = None
    live_final: dict[str, Any] | None = None
    live_gate_report: dict[str, Any] | None = None
    if live_pair is not None:
        live_baseline_file, live_final_file = live_pair
        live_baseline = _load(live_baseline_file)
        live_final = _load(live_final_file)
        _copy_result_tree(live_baseline_file, output_dir / "results" / "live_provider" / "baseline")
        _copy_result_tree(live_final_file, output_dir / "results" / "live_provider" / "final")
        live_gate_report = evaluate_gates(live_baseline, live_final)
        live_gate_report["baseline_file"] = "results/live_provider/baseline/results.json"
        live_gate_report["final_file"] = "results/live_provider/final/results.json"
        (output_dir / "results" / "official_live_quality_gates.json").write_text(
            json.dumps(live_gate_report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        try:
            live_no_verifier = _latest_result(results_dir, "final", "no_verifier", execution_mode="live_provider")
            _copy_result_tree(live_no_verifier, output_dir / "results" / "live_provider" / "ablation_no_verifier")
        except FileNotFoundError:
            pass

    ablation_names = (
        "no_verifier",
        "no_evidence_enforcement",
        "no_deterministic_checks",
        "no_tool_output_normalization",
        "it5_subagents",
    )
    ablation_summary: dict[str, Any] = {
        "schema_version": "1.0",
        "reference_final": final.get("meta", {}),
        "ablations": {},
    }
    for ablation in ablation_names:
        try:
            ablation_file = _latest_result(results_dir, "final", ablation, execution_mode="offline_fixture")
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
        "| Run | CBR | Precision | Critical evidence | Unsupported critical | Successful run rate | Runtime | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    reference_metrics = final.get("aggregate", {}).get("all", {})
    rows = [("final (Verifier ON)", reference_metrics)]
    rows.extend(
        (name, data["aggregate_all"])
        for name, data in ablation_summary["ablations"].items()
    )
    for name, metrics in rows:
        cost = metrics.get("total_cost", metrics.get("total_cost_usd", 0.0))
        ablation_lines.append(
            f"| `{name}` | {metrics.get('cbr', 0.0):.4f} | {metrics.get('precision', 0.0):.4f} | "
            f"{metrics.get('critical_evidence_coverage', 0.0):.4f} | "
            f"{metrics.get('unsupported_critical_total', 0)} | "
            f"{metrics.get('successful_run_rate', 0.0):.4f} | "
            f"{metrics.get('total_runtime_ms', 0.0):.0f} ms | "
            f"${cost:.4f} |"
        )
    (output_dir / "results" / "ablations" / "comparison.md").write_text(
        "\n".join(ablation_lines)
        + "\n\n## Interpretation\n\n"
        + "- Verifier ON and `no_verifier` have the same metrics on these frozen, "
          "non-adversarial cases; this does not support a metric-lift claim for "
          "verification.\n"
        + "- Evidence enforcement ON/OFF also matches because no unsupported "
          "critical candidate was emitted in this run.\n"
        + "- `no_deterministic_checks` and It5 show the meaningful negative controls: "
          "removing deterministic evidence or adding specialized agents reduced "
          "quality.\n",
        encoding="utf-8",
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
    live_result = live_pair[1] if live_pair is not None else failed_live_result
    live_payload = _load(live_result) if live_result is not None else {}
    live_meta = live_payload.get("meta", {})
    live_aggregate = live_payload.get("aggregate", {})
    live_execution_mode = live_meta.get("execution_mode")
    if live_execution_mode is None and live_meta.get("model_id", "").startswith(("gemini-", "grok-")):
        live_execution_mode = "live_provider"
    official_status = {
        "schema_version": "1.0",
        "status": "available" if live_pair is not None else "unavailable",
        "measurement": "official_llm_baseline_final",
        "provider": live_meta.get("provider") if live_meta else None,
        "model_id": live_meta.get("model_id") if live_meta else None,
        "successful_live_pair": live_pair is not None,
        "quality_gates_passed": live_gate_report.get("passed") if live_gate_report else None,
        "reason": (
            "A successful 12-case live-provider baseline/final pair is included. "
            "Its official quality gate result is preserved without substitution."
            if live_pair is not None
            else "No successful live-provider baseline/final pair is available in this bundle."
        ),
        "offline_fixture_results_are_not_official_substitute": True,
        "observed_live_attempt": {
            "run_label": live_meta.get("run_label") if live_meta else None,
            "mode": live_meta.get("mode") if live_meta else None,
            "execution_mode": live_execution_mode,
            "successful_run_rate": live_aggregate.get("all", {}).get("successful_run_rate") if live_aggregate else None,
            "results_file": (
                "results/live_provider/final/results.json"
                if live_pair is not None
                else "results/live_provider_attempt/results.json" if failed_live_result is not None else None
            ),
        },
        "rerun": "make baseline-live && make evaluate-live",
    }
    (output_dir / "results" / "official_llm_status.json").write_text(
        json.dumps(official_status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "results" / "README.md").write_text(
        "# Evaluation result provenance\n\n"
        "The baseline, final, and ablation directories in this bundle are the "
        "reproducible `releaseguard-offline-v1` fixture simulation. Their numeric "
        "quality gates are not official LLM benchmark results. The official live "
        "measurement status is recorded in `official_llm_status.json`; a successful "
        "pair is stored under `live_provider/`, while failed attempts remain separate.\n\n"
        "To create an official comparison with a fresh provider key and quota, run "
        "`make baseline-live`, `make evaluate-live`, and then use "
        "`scripts/check_quality_gates.py --require-live`.\n",
        encoding="utf-8",
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
    it5_cost = it5_metrics.get("total_cost", it5_metrics.get("total_cost_usd"))
    (it5_dir / "README.md").write_text(
        "# Removed experiment: It5 specialized subagents\n\n"
        "This is the executed comparison requested by the changelog. It runs CI,\n"
        "security, and test specialists and combines their bounded outputs before\n"
        "the same verifier and decision policy. The measured result is stored under\n"
        "`results/ablations/it5_subagents/`.\n\n"
        f"All-case CBR: {it5_metrics.get('cbr', 'N/A')}\n"
        f"All-case precision: {it5_metrics.get('precision', 'N/A')}\n"
        f"All-case decision accuracy: {it5_metrics.get('decision_accuracy', 'N/A')}\n"
        f"Critical evidence coverage: {it5_metrics.get('critical_evidence_coverage', 'N/A')}\n"
        f"Unsupported critical findings: {it5_metrics.get('unsupported_critical_total', 'N/A')}\n"
        f"All-case successful run rate: {it5_metrics.get('successful_run_rate', 'N/A')}\n"
        f"Runtime: {it5_metrics.get('total_runtime_ms', 'N/A')} ms\n"
        + (f"Cost: ${it5_cost:.4f}\n" if isinstance(it5_cost, (int, float)) else f"Cost: {it5_cost or 'N/A'}\n")
        + "Decision: REMOVE — the extra specialists reduced CBR on the frozen cases.\n",
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
        "`releaseguard_demo.mp4` is an approximately 100-second AVFoundation-rendered "
        "walkthrough. It covers the persona and bottleneck, the baseline and final "
        "commands, Analyzer -> Verifier on case 12, redaction/private-repository "
        "guards, the changelog and removed It5 experiment, reproduction commands, "
        "and the honest offline/live measurement boundary.\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "# ReleaseGuard submission bundle\n\n"
        "This directory is a curated, redacted selection for review. It contains\n"
        "the 12-case offline-fixture baseline/final simulation and comparison,\n"
        "ablations, representative Analyzer and Verifier trajectories, the case 12\n"
        "report, the executed removed experiment, quality-gate output, official LLM\n"
        "status, and a walkthrough video. The offline numbers are explicitly not\n"
        "official live-provider measurements. The completed xAI pair and its FAIL\n"
        "gate are stored separately from both fixture results and failed attempts.\n"
        "Local runtime directories and secrets are excluded by the ZIP packager.\n",
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
            "results/README.md",
            "results/official_llm_status.json",
            "results/ablations/comparison.json",
            "trajectories/analyzer_case_12.jsonl",
            "trajectories/verifier_case_12.jsonl",
            "case_12/report.json",
            "removed_experiment/README.md",
            "video/releaseguard_demo.mp4",
        ],
    }
    if failed_live_result is not None:
        manifest["live_provider_attempt"] = "results/live_provider_attempt/results.json"
    if live_pair is not None:
        manifest["required_artifacts"].append("results/official_live_quality_gates.json")
        manifest["official_live_pair"] = {
            "baseline": "results/live_provider/baseline/results.json",
            "final": "results/live_provider/final/results.json",
            "quality_gates": "results/official_live_quality_gates.json",
        }
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
