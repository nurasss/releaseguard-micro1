# path: app/checks/release.py
"""DC-05: manifest/version metadata consistency vs the requested release ref."""

from __future__ import annotations

import json
import re
import tomllib

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

_REF_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)")


def _extract_ref_version(ref: str) -> str | None:
    m = _REF_VERSION_RE.search(ref)
    return m.group(1) if m else None


def _find_manifest(tree_paths: set[str]) -> str | None:
    if "pyproject.toml" in tree_paths:
        return "pyproject.toml"
    if "package.json" in tree_paths:
        return "package.json"
    return None


def _manifest_version(source: RepositorySource, manifest_path: str) -> tuple[str | None, str]:
    content = source.read_file(manifest_path).content
    if manifest_path.endswith(".toml"):
        try:
            data = tomllib.loads(content)
        except Exception:
            return None, content
        version = data.get("project", {}).get("version")
        return version, content
    if manifest_path.endswith("package.json"):
        try:
            data = json.loads(content)
        except Exception:
            return None, content
        return data.get("version"), content
    return None, content


def check_version_metadata(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    ref_version = _extract_ref_version(resolved.requested_ref)
    tree_paths = {e.path for e in source.get_tree()}
    manifest_path = _find_manifest(tree_paths)

    if ref_version is None or manifest_path is None:
        return DeterministicCheckResult(
            check_id="DC-05",
            name="Release version metadata consistency",
            status=CheckStatus.not_applicable,
            details=(
                "Requested ref does not encode a semantic version (vX.Y.Z), or no manifest "
                "(pyproject.toml/package.json) was found."
            ),
            evidence_ids=[],
        )

    manifest_version, content = _manifest_version(source, manifest_path)
    ev = evidence_store.add(
        source_type=SourceType.manifest,
        source_path=manifest_path,
        summary=f"Manifest version: {manifest_version!r}",
        payload={"manifest_version": manifest_version, "requested_ref": resolved.requested_ref},
        content=content,
    )

    if manifest_version is None:
        return DeterministicCheckResult(
            check_id="DC-05",
            name="Release version metadata consistency",
            status=CheckStatus.error,
            details=f"Could not parse a version field from {manifest_path}.",
            evidence_ids=[ev.id],
        )

    if str(manifest_version).strip() != ref_version:
        return DeterministicCheckResult(
            check_id="DC-05",
            name="Release version metadata consistency",
            status=CheckStatus.fail,
            details=(
                f"Manifest {manifest_path} declares version {manifest_version!r}, which does not "
                f"match requested ref {resolved.requested_ref!r} (expected {ref_version!r})."
            ),
            evidence_ids=[ev.id],
        )

    return DeterministicCheckResult(
        check_id="DC-05",
        name="Release version metadata consistency",
        status=CheckStatus.pass_,
        details=(
            f"Manifest {manifest_path} version {manifest_version!r} matches requested ref "
            f"{resolved.requested_ref!r}."
        ),
        evidence_ids=[ev.id],
    )
