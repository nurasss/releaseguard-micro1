# path: app/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.orchestration.runner import AuditRunner


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="releaseguard",
        description="ReleaseGuard: Read-only automated repository release readiness auditor.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    audit_parser = subparsers.add_parser("audit", help="Run a release readiness audit")
    target_group = audit_parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--case",
        type=str,
        help="Path to local fixture case directory (e.g. eval/cases/case_01)",
    )
    target_group.add_argument(
        "--repo",
        type=str,
        help="GitHub repository URL or slug (e.g. https://github.com/owner/repo)",
    )

    audit_parser.add_argument(
        "--ref",
        type=str,
        default="main",
        help="Git ref (branch, tag, release, or commit SHA). Default is 'main'.",
    )
    audit_parser.add_argument(
        "--mode",
        choices=["baseline", "final"],
        default="baseline",
        help="Audit mode: 'baseline' (official B1) or 'final'. Default is 'baseline'.",
    )
    audit_parser.add_argument(
        "--model",
        type=str,
        help="Override LLM model ID (e.g. gemini-2.5-flash)",
    )
    audit_parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="Maximum tool calling iterations (default: 10)",
    )
    audit_parser.add_argument(
        "--deadline",
        type=int,
        help="Timeout deadline in seconds for entire audit (default from settings: 300s)",
    )
    audit_parser.add_argument(
        "--out",
        type=str,
        help="Base directory for output runs and artifacts (default: ./runs)",
    )
    audit_parser.add_argument(
        "--db",
        type=str,
        help="Path to SQLite database file (default: ./runs/releaseguard.sqlite3)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "audit":
        settings = get_settings()

        # Apply CLI overrides to settings
        if args.model:
            settings.model_id = args.model
        if args.deadline:
            settings.audit_deadline_s = args.deadline
        if args.out:
            settings.data_dir = Path(args.out).resolve()
        if args.db:
            settings.db_path = Path(args.db).resolve()

        runner = AuditRunner(settings=settings)

        if args.case:
            outcome = runner.run_case(case_dir=args.case, mode=args.mode, max_turns=args.max_turns)
        else:
            outcome = runner.run_repository(repository_url=args.repo, ref=args.ref, mode=args.mode, max_turns=args.max_turns)

        run = outcome.run
        report = outcome.report

        print("=" * 60)
        print("ReleaseGuard Audit Result")
        print("=" * 60)
        print(f"Audit Run ID:     {run.id}")
        print(f"Repository:       {run.repository_url}")
        print(f"Requested Ref:    {run.requested_ref}")
        print(f"Resolved SHA:     {run.commit_sha}")
        print(f"Mode:             {run.mode}")
        print(f"Run Status:       {run.status.value}")
        print(f"Final Decision:   {report.decision.value}")
        print(f"Findings Count:   {len(report.findings)}")
        print(f"Evidence Count:   {len(report.evidence)}")
        print(f"Runtime:          {report.runtime_ms} ms")
        print(f"Estimated Cost:   ${report.estimated_cost_usd:.4f}")
        print(f"Artifacts Dir:    {outcome.artifacts_dir}")
        if outcome.integrity_violations:
            print(f"Integrity Alerts: {len(outcome.integrity_violations)}")
            for v in outcome.integrity_violations[:5]:
                print(f"  - {v}")
        print("=" * 60)

        if run.status.value == "failed":
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
