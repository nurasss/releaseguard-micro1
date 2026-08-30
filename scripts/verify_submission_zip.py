"""Verify and safely extract a ReleaseGuard submission archive."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path


REQUIRED_MEMBERS = {
    "README.md",
    "submission/manifest.json",
    "submission/results/baseline/results.json",
    "submission/results/final/results.json",
    "submission/results/comparison.json",
    "submission/results/comparison.md",
    "submission/results/quality_gates.json",
    "submission/results/README.md",
    "submission/results/official_llm_status.json",
    "submission/results/ablations/comparison.json",
    "submission/trajectories/analyzer_case_12.jsonl",
    "submission/trajectories/verifier_case_12.jsonl",
    "submission/case_12/report.json",
    "submission/removed_experiment/README.md",
    "submission/video/releaseguard_demo.mp4",
}


def verify_archive(archive: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        missing = sorted(REQUIRED_MEMBERS - names)
        if missing:
            errors.append(f"missing required member(s): {', '.join(missing)}")

        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            basename = Path(name).name
            if basename.startswith(".env") and basename not in {".env.example", ".env.sample", ".env.template"}:
                errors.append(f"secret dotenv file present: {name}")
            if name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm")):
                errors.append(f"local database present: {name}")
            if any(part in {".git", "__pycache__", ".pytest_cache", ".venv", "venv"} for part in Path(name).parts):
                errors.append(f"runtime/VCS member present: {name}")
            if name.startswith(("runs/", "trajectories/", "artifacts/", "eval/results/")):
                errors.append(f"uncurated runtime member present: {name}")
            # Refuse Unix symlinks so extraction cannot escape its destination.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                errors.append(f"symlink member present: {name}")

        if not errors:
            with tempfile.TemporaryDirectory(prefix="releaseguard-unzip-") as temp_dir:
                target = Path(temp_dir)
                zf.extractall(target)
                try:
                    json.loads((target / "submission" / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"extracted manifest is not valid JSON: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a ReleaseGuard submission ZIP")
    parser.add_argument("archive", nargs="?", default="dist/releaseguard_submission.zip")
    args = parser.parse_args(argv)
    archive = Path(args.archive)
    if not archive.exists():
        print(f"Archive not found: {archive}", file=sys.stderr)
        return 1
    errors = verify_archive(archive)
    if errors:
        print("Submission ZIP verification failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Submission ZIP verified: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
