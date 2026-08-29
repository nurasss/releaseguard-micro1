"""Deterministic commit SHA computation for evaluation fixtures.

Implements the specification in EVALUATION_SPEC.md §7:
1. For every file under repo/, compute its relative path using forward slashes and the SHA-256 of its bytes.
2. Form lines `<relpath>:<sha256hex>`.
3. Sort lines lexicographically by `relpath`.
4. Join lines with `\\n`.
5. SHA-256 the joined UTF-8 bytes and take the first 40 hexadecimal characters as `commit_sha`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_repo_commit_sha(repo_dir: Path | str) -> str:
    """Compute deterministic commit SHA for a fixture repository directory."""
    repo_path = Path(repo_dir).resolve()
    entries: list[tuple[str, str]] = []

    for file_path in repo_path.rglob("*"):
        if file_path.is_file():
            rel_path = file_path.relative_to(repo_path).as_posix()
            file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            entries.append((rel_path, file_hash))

    entries.sort(key=lambda item: item[0])
    manifest_lines = [f"{rel_path}:{file_hash}" for rel_path, file_hash in entries]
    joined_manifest = "\n".join(manifest_lines)
    full_sha = hashlib.sha256(joined_manifest.encode("utf-8")).hexdigest()
    return full_sha[:40]
