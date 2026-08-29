# path: app/sources/fixture.py
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path

from app.schemas.evidence import content_hash_of
from app.sources.base import (
    MAX_READ_FILE_CHARS,
    MAX_READ_FILE_LINES,
    MAX_SEARCH_HITS,
    MAX_SEARCH_LINE_CHARS,
    MAX_TEST_ERROR_MESSAGE_CHARS,
    MAX_TREE_ENTRIES,
    FileSlice,
    RepositorySource,
    ResolvedRef,
    SearchHit,
    TreeEntry,
)
from app.sources.errors import (
    FileNotFoundInRepoError,
    InvalidPathError,
    PathEscapeError,
    UnknownRefError,
)
from eval.fixture_sha import compute_repo_commit_sha


class LocalFixtureSource(RepositorySource):
    """Repository source adapter for local evaluation case fixtures."""

    def __init__(self, case_dir: Path | str) -> None:
        self.case_dir = Path(case_dir).resolve()
        self.repo_dir = (self.case_dir / "repo").resolve()
        self.artifacts_dir = (self.case_dir / "artifacts").resolve()

    def _safe_repo_path(self, path_str: str) -> Path:
        """Validate that path_str does not escape repo_dir and exists as a file."""
        if not path_str or not isinstance(path_str, str):
            raise InvalidPathError("Path must be a non-empty string")

        # Reject absolute paths (POSIX and Windows drive letters)
        if (
            os.path.isabs(path_str)
            or Path(path_str).is_absolute()
            or path_str.startswith("/")
            or path_str.startswith("\\")
            or (len(path_str) > 1 and path_str[1] == ":")
        ):
            raise PathEscapeError(f"Absolute paths are forbidden: {path_str}")

        # Resolve target and check for path traversal escape
        try:
            target = (self.repo_dir / path_str).resolve()
        except Exception as exc:
            raise InvalidPathError(f"Invalid path format: {path_str}") from exc

        if not target.is_relative_to(self.repo_dir):
            raise PathEscapeError(f"Path escapes repository boundary: {path_str}")

        if not target.exists() or not target.is_file():
            raise FileNotFoundInRepoError(f"File not found in repository: {path_str}")

        return target

    def resolve_ref(self, ref: str) -> ResolvedRef:
        commit_sha = compute_repo_commit_sha(self.repo_dir)

        metadata = self.get_repository_metadata()
        branches = metadata.get("branches", [])
        default_branch = metadata.get("default_branch", "main")
        tags = metadata.get("tags", [])
        releases = metadata.get("releases", [])

        ref_type: str | None = None
        if ref in branches or ref == default_branch:
            ref_type = "branch"
        elif ref in tags:
            ref_type = "tag"
        elif ref in releases:
            ref_type = "release"
        elif ref == commit_sha or (len(ref) >= 7 and commit_sha.startswith(ref)):
            ref_type = "commit"

        if ref_type is None:
            raise UnknownRefError(f"Ref {ref!r} not found in repository metadata or commit history")

        return ResolvedRef(
            requested_ref=ref,
            commit_sha=commit_sha,
            ref_type=ref_type,  # type: ignore[arg-type]
        )

    def get_repository_metadata(self) -> dict:
        meta_file = self.artifacts_dir / "repository_metadata.json"
        if meta_file.exists():
            try:
                raw = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
        else:
            raw = {}

        default_branch = raw.get("default_branch", "main")
        branches = raw.get("branches", [default_branch])
        if default_branch not in branches:
            branches.insert(0, default_branch)

        return {
            "default_branch": default_branch,
            "description": raw.get("description", ""),
            "branches": branches,
            "tags": raw.get("tags", []),
            "releases": raw.get("releases", []),
            "topics": raw.get("topics", []),
        }

    def get_tree(self) -> list[TreeEntry]:
        if not self.repo_dir.exists():
            return []

        all_files = [p for p in self.repo_dir.rglob("*") if p.is_file()]
        all_files.sort(key=lambda p: p.relative_to(self.repo_dir).as_posix())

        entries: list[TreeEntry] = []
        for file_path in all_files[:MAX_TREE_ENTRIES]:
            rel = file_path.relative_to(self.repo_dir).as_posix()
            entries.append(TreeEntry(path=rel, size_bytes=file_path.stat().st_size))

        return entries

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> FileSlice:
        target = self._safe_repo_path(path)
        content_bytes = target.read_bytes()
        text = content_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)

        if start_line is not None or end_line is not None:
            s_line = start_line if start_line is not None else 1
            e_line = end_line if end_line is not None else total_lines
            s_line = max(1, s_line)
            e_line = min(total_lines, max(s_line, e_line))

            selected_lines = lines[s_line - 1 : e_line] if total_lines > 0 else []
            slice_text = "\n".join(selected_lines)
            truncated = False

            if len(slice_text) > MAX_READ_FILE_CHARS:
                slice_text = slice_text[:MAX_READ_FILE_CHARS]
                truncated = True

            content_hash = content_hash_of(slice_text)
            return FileSlice(
                path=path,
                start_line=s_line if total_lines > 0 else 0,
                end_line=e_line if total_lines > 0 else 0,
                total_lines=total_lines,
                content=slice_text,
                truncated=truncated,
                content_hash=content_hash,
            )

        # Default reading window: up to MAX_READ_FILE_LINES and MAX_READ_FILE_CHARS
        truncated = False
        selected_lines = lines[:MAX_READ_FILE_LINES]
        if total_lines > MAX_READ_FILE_LINES:
            truncated = True

        slice_text = "\n".join(selected_lines)
        if len(slice_text) > MAX_READ_FILE_CHARS:
            slice_text = slice_text[:MAX_READ_FILE_CHARS]
            truncated = True

        end_l = min(total_lines, MAX_READ_FILE_LINES) if total_lines > 0 else 0
        content_hash = content_hash_of(slice_text)
        return FileSlice(
            path=path,
            start_line=1 if total_lines > 0 else 0,
            end_line=end_l,
            total_lines=total_lines,
            content=slice_text,
            truncated=truncated,
            content_hash=content_hash,
        )

    def search_files(
        self,
        pattern: str,
        glob: str | None = None,
    ) -> list[SearchHit]:
        if not self.repo_dir.exists() or not pattern:
            return []

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        all_files = [p for p in self.repo_dir.rglob("*") if p.is_file()]
        all_files.sort(key=lambda p: p.relative_to(self.repo_dir).as_posix())

        hits: list[SearchHit] = []
        for file_path in all_files:
            rel = file_path.relative_to(self.repo_dir).as_posix()
            if glob and not fnmatch.fnmatch(rel, glob):
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for idx, line in enumerate(lines, start=1):
                if regex.search(line):
                    hits.append(
                        SearchHit(
                            path=rel,
                            line_number=idx,
                            line=line[:MAX_SEARCH_LINE_CHARS],
                        )
                    )
                    if len(hits) >= MAX_SEARCH_HITS:
                        return hits

        return hits

    def get_workflow_files(self) -> list[str]:
        wf_dir = self.repo_dir / ".github" / "workflows"
        if not wf_dir.exists() or not wf_dir.is_dir():
            return []
        files = [p.relative_to(self.repo_dir).as_posix() for p in wf_dir.rglob("*") if p.is_file()]
        return sorted(files)

    def get_workflow_runs(self) -> list[dict]:
        runs_file = self.artifacts_dir / "github_actions_runs.json"
        if not runs_file.exists():
            return []
        try:
            raw = json.loads(runs_file.read_text(encoding="utf-8"))
        except Exception:
            return []

        if isinstance(raw, list):
            runs = raw
        elif isinstance(raw, dict):
            runs = raw.get("workflow_runs", [])
        else:
            runs = []

        normalized: list[dict] = []
        for r in runs:
            if not isinstance(r, dict):
                continue
            normalized.append(
                {
                    "workflow_name": r.get("name", r.get("workflow_name", "")),
                    "path": r.get("path", ""),
                    "head_branch": r.get("head_branch", ""),
                    "event": r.get("event", ""),
                    "conclusion": r.get("conclusion", ""),
                    "created_at": r.get("created_at", ""),
                }
            )
        return normalized

    def get_test_report(self) -> dict | None:
        report_file = self.artifacts_dir / "test_report.json"
        if not report_file.exists():
            return None
        try:
            raw = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            return None

        failures: list[dict] = []
        for f in raw.get("failures", []):
            if not isinstance(f, dict):
                continue
            msg = str(f.get("message", ""))
            failures.append(
                {
                    "test": f.get("test", ""),
                    "error_type": f.get("error_type", ""),
                    "message": msg[:MAX_TEST_ERROR_MESSAGE_CHARS],
                }
            )

        return {
            "total": int(raw.get("total", 0)),
            "passed": int(raw.get("passed", 0)),
            "failed": int(raw.get("failed", 0)),
            "failures": failures,
        }

    def get_build_report(self) -> dict | None:
        build_file = self.artifacts_dir / "build_report.json"
        if not build_file.exists():
            return None
        try:
            raw = json.loads(build_file.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {"content": raw}
        except Exception:
            return None
