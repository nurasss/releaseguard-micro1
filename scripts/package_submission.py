# path: scripts/package_submission.py
"""Build a submission ZIP archive that never includes local secrets or runtime artifacts.

Unlike a manual "zip the whole folder" step, this walks the tree explicitly and
prunes anything that must never leave a developer's machine: .env files, VCS
metadata, Python caches, local databases, and runtime output (runs/,
trajectories/, artifacts/). It does not rely solely on .gitignore / git tracking,
so it stays safe even for files that were added but not yet committed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

# Directory names pruned entirely, wherever they occur in the tree.
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
}

# Directories excluded only at the repository root (matches the /runs/,
# /trajectories/, /artifacts/ leading-slash semantics in .gitignore — nested
# copies such as eval/cases/*/artifacts/ are frozen benchmark data and must
# stay in the archive). "dist" holds packaging outputs (this script's own
# ZIPs) and must never be walked back into the next archive.
EXCLUDED_ROOT_DIRS = {"runs", "trajectories", "artifacts", "dist"}

# The evaluation harness writes timestamped local results here.  The curated
# copies under submission/results are the only evaluation outputs intended for
# the archive.
EXCLUDED_ROOT_PATHS = {("eval", "results")}

# Root-relative file/dir names excluded outright.
EXCLUDED_ROOT_NAMES = {"releaseguard.egg-info"}

# Filename suffixes treated as local databases.
EXCLUDED_DB_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm")

# .env variants that are safe to ship (templates, never real secrets).
ALLOWED_DOTENV_NAMES = {".env.example", ".env.sample", ".env.template"}


def _is_secret_env_file(name: str) -> bool:
    return name.startswith(".env") and name not in ALLOWED_DOTENV_NAMES


def _should_skip_dir(dir_name: str, rel_parts: tuple[str, ...]) -> bool:
    if dir_name in EXCLUDED_DIR_NAMES:
        return True
    if not rel_parts and dir_name in EXCLUDED_ROOT_DIRS:
        return True
    if not rel_parts and dir_name in EXCLUDED_ROOT_NAMES:
        return True
    if rel_parts + (dir_name,) in EXCLUDED_ROOT_PATHS:
        return True
    return False


def _should_skip_file(file_name: str) -> bool:
    if _is_secret_env_file(file_name):
        return True
    if file_name.endswith(EXCLUDED_DB_SUFFIXES):
        return True
    if file_name.endswith((".pyc", ".pyo")):
        return True
    return False


def iter_archive_members(source_dir: Path, exclude_path: Path | None = None) -> list[Path]:
    """Return every file path (relative to source_dir) that should be packaged.

    exclude_path, if given, is resolved and skipped even if it lives inside
    source_dir — this is what stops the archive's own output ZIP from being
    walked back into itself on a second run.
    """
    source_dir = source_dir.resolve()
    resolved_exclude = exclude_path.resolve() if exclude_path is not None else None
    members: list[Path] = []

    def walk(current: Path, rel_parts: tuple[str, ...]) -> None:
        for entry in sorted(current.iterdir()):
            rel = rel_parts + (entry.name,)
            if resolved_exclude is not None and entry.resolve() == resolved_exclude:
                continue
            if entry.is_dir():
                if _should_skip_dir(entry.name, rel_parts):
                    continue
                walk(entry, rel)
            elif entry.is_file():
                if _should_skip_file(entry.name):
                    continue
                members.append(Path(*rel))

    walk(source_dir, ())
    return members


def build_archive(source_dir: Path | str, output_path: Path | str) -> Path:
    """Package source_dir into a ZIP at output_path, excluding secrets/runtime artifacts.

    Safe to call repeatedly with the same output_path: the output file itself
    (even mid-write) is always excluded from its own member list.
    """
    source_dir = Path(source_dir).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    members = iter_archive_members(source_dir, exclude_path=output_path)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in members:
            zf.write(source_dir / rel_path, arcname=str(rel_path))

    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a secrets-free ReleaseGuard submission archive")
    parser.add_argument("--source", default=".", help="Project root to package (default: cwd)")
    parser.add_argument("--out", default="dist/releaseguard_submission.zip", help="Output ZIP path")
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Do not refresh submission/ from the latest evaluation artifacts",
    )
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    if not args.skip_prepare and source == Path.cwd().resolve():
        python = source / ".venv" / "bin" / "python"
        interpreter = str(python) if python.exists() else sys.executable
        prepare = subprocess.run(
            [interpreter, "scripts/prepare_submission.py"],
            cwd=source,
            check=False,
        )
        if prepare.returncode != 0:
            return prepare.returncode
        # Keep the gate decision beside the curated artifacts. A failed gate is
        # retained in the report for honest review; packaging itself still
        # produces the archive so the failure cannot be hidden.
        gate = subprocess.run(
            [interpreter, "scripts/check_quality_gates.py", "--out", "/tmp/releaseguard-quality-gates.json"],
            cwd=source,
            check=False,
        )
        if gate.returncode != 0:
            print("Warning: one or more quality gates failed; archive retains the gate report.", file=sys.stderr)

    output = build_archive(args.source, args.out)
    with zipfile.ZipFile(output) as zf:
        member_count = len(zf.namelist())
    print(f"Wrote {output} ({member_count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
