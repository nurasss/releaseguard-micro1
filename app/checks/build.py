# path: app/checks/build.py
"""DC-06: lockfile presence when a manifest implies one is expected.
DC-07: whether a build/release command is declared, and whether a recorded
build execution (if any) succeeded.
"""

from __future__ import annotations

import json
import re
import tomllib

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

_MANIFEST_NAMES = ("pyproject.toml", "package.json", "Cargo.toml", "go.mod")
_LOCKFILE_NAMES = {
    "requirements.lock",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
}


def check_lockfile_presence(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    tree_paths = {e.path for e in source.get_tree()}
    manifest_present = any(p in tree_paths for p in _MANIFEST_NAMES)

    if not manifest_present:
        return DeterministicCheckResult(
            check_id="DC-06",
            name="Lockfile presence",
            status=CheckStatus.not_applicable,
            details="No dependency manifest (pyproject.toml/package.json/Cargo.toml/go.mod) found.",
            evidence_ids=[],
        )

    lockfiles = sorted(p for p in tree_paths if p.rsplit("/", 1)[-1] in _LOCKFILE_NAMES)

    if lockfiles:
        ev = evidence_store.add(
            source_type=SourceType.lockfile,
            source_path=lockfiles[0],
            summary=f"Lockfile present: {lockfiles[0]}",
            payload={"lockfiles": lockfiles},
        )
        return DeterministicCheckResult(
            check_id="DC-06",
            name="Lockfile presence",
            status=CheckStatus.pass_,
            details=f"Lockfile(s) found: {lockfiles}.",
            evidence_ids=[ev.id],
        )

    ev = evidence_store.add(
        source_type=SourceType.deterministic_check,
        source_path="<repository tree>",
        summary="No lockfile found for dependency manifest",
        payload={"manifest_present": True},
    )
    return DeterministicCheckResult(
        check_id="DC-06",
        name="Lockfile presence",
        status=CheckStatus.warn,
        details=(
            "A dependency manifest is present but no recognized lockfile was found; "
            "reproducible installs are not guaranteed."
        ),
        evidence_ids=[ev.id],
    )


def _find_declared_build_command(source: RepositorySource, tree_paths: set[str]) -> list[str]:
    declared: list[str] = []

    if "pyproject.toml" in tree_paths:
        try:
            content = source.read_file("pyproject.toml").content
            data = tomllib.loads(content)
        except Exception:
            data = {}
        scripts = data.get("project", {}).get("scripts", {}) if isinstance(data, dict) else {}
        for name, target in scripts.items():
            if "build" in name.lower() or "release" in name.lower():
                declared.append(f"pyproject.toml [project.scripts] {name} = {target}")

    if "package.json" in tree_paths:
        try:
            content = source.read_file("package.json").content
            data = json.loads(content)
        except Exception:
            data = {}
        scripts = (data.get("scripts") or {}) if isinstance(data, dict) else {}
        for name, cmd in scripts.items():
            if "build" in name.lower():
                declared.append(f"package.json scripts.{name} = {cmd}")

    if "Makefile" in tree_paths:
        try:
            content = source.read_file("Makefile").content
        except Exception:
            content = ""
        if re.search(r"^build\s*:", content, re.MULTILINE):
            declared.append("Makefile target 'build'")

    return declared


def check_build_command(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    tree_paths = {e.path for e in source.get_tree()}
    declared = _find_declared_build_command(source, tree_paths)
    build_report = source.get_build_report()

    if build_report is not None:
        ev = evidence_store.add(
            source_type=SourceType.build_result,
            source_path="build_report",
            summary=f"Build report exit_code={build_report.get('exit_code')}",
            payload=build_report,
        )
        exit_code = build_report.get("exit_code", 0)
        if exit_code != 0:
            stderr_tail = str(build_report.get("stderr_tail", ""))[:300]
            return DeterministicCheckResult(
                check_id="DC-07",
                name="Build/release command",
                status=CheckStatus.fail,
                details=(
                    f"Recorded build run {build_report.get('command', '')!r} exited with code "
                    f"{exit_code}: {stderr_tail}"
                ),
                evidence_ids=[ev.id],
            )
        return DeterministicCheckResult(
            check_id="DC-07",
            name="Build/release command",
            status=CheckStatus.pass_,
            details=f"Recorded build run {build_report.get('command', '')!r} completed with exit_code 0.",
            evidence_ids=[ev.id],
        )

    if declared:
        ev = evidence_store.add(
            source_type=SourceType.deterministic_check,
            source_path="<repository tree>",
            summary="Build/release command declared",
            payload={"declared": declared},
        )
        return DeterministicCheckResult(
            check_id="DC-07",
            name="Build/release command",
            status=CheckStatus.pass_,
            details=(
                f"Build/release command declared: {'; '.join(declared)}. No execution report "
                "was available to verify it runs successfully."
            ),
            evidence_ids=[ev.id],
        )

    return DeterministicCheckResult(
        check_id="DC-07",
        name="Build/release command",
        status=CheckStatus.not_applicable,
        details=(
            "No build/release command declared (no matching pyproject.toml [project.scripts], "
            "package.json scripts, or Makefile 'build' target) and no build report available."
        ),
        evidence_ids=[],
    )
