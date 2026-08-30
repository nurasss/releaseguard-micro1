"""Fail on recognisable secrets in Git-tracked files without printing values."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.security.redaction import (
    SAFE_TEMPLATE_NAMES,
    SENSITIVE_BASENAMES,
    SENSITIVE_SUFFIXES,
    find_secrets,
)


def _tracked_secret_filename(relative: str) -> bool:
    name = Path(relative).name.lower()
    if name.startswith(".env") and name not in SAFE_TEMPLATE_NAMES:
        return True
    return name in SENSITIVE_BASENAMES or name.endswith(tuple(SENSITIVE_SUFFIXES))


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / item for item in result.stdout.decode("utf-8").split("\0") if item]


def main() -> int:
    root = Path.cwd().resolve()
    findings: list[str] = []
    try:
        files = tracked_files(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Secret scan could not list tracked files: {exc}", file=sys.stderr)
        return 1

    for path in files:
        relative = path.relative_to(root).as_posix()
        # The test suite deliberately constructs synthetic provider tokens and
        # private-key headers to verify the redactor. They are not repository
        # credentials and are covered by the unit tests themselves.
        if relative.startswith("tests/"):
            continue
        if _tracked_secret_filename(relative):
            findings.append(f"{relative}: sensitive filename is tracked")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, pattern_name, _masked in find_secrets(text):
            findings.append(f"{relative}:{line_number}: {pattern_name}")

    if findings:
        print("Secret scan failed (values are intentionally not printed):", file=sys.stderr)
        print("\n".join(f"- {item}" for item in findings), file=sys.stderr)
        return 1
    print(f"Secret scan passed for {len(files)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
