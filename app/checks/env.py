# path: app/checks/env.py
"""DC-08: required environment variables are documented."""

from __future__ import annotations

import re

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

# os.environ["FOO"] / os.environ['FOO'] with no default -> required.
_REQUIRED_ENV_RE = re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]")
_DOC_VAR_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_DOC_FILES = (".env.example", ".env.sample", "README.md")


def _documented_vars(text: str) -> set[str]:
    return set(_DOC_VAR_RE.findall(text))


def check_required_env_vars(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    hits = source.search_files(r"os\.environ\[", glob=None)
    required: dict[str, list[str]] = {}
    for h in hits:
        m = _REQUIRED_ENV_RE.search(h.line)
        if m:
            required.setdefault(m.group(1), []).append(f"{h.path}:{h.line_number}")

    if not required:
        return DeterministicCheckResult(
            check_id="DC-08",
            name="Required environment variable documentation",
            status=CheckStatus.not_applicable,
            details="No required (default-less) environment variable access detected in source.",
            evidence_ids=[],
        )

    tree_paths = {e.path for e in source.get_tree()}
    documented: set[str] = set()
    for doc_path in _DOC_FILES:
        if doc_path in tree_paths:
            try:
                content = source.read_file(doc_path).content
            except Exception:
                continue
            documented |= _documented_vars(content)

    evidence_ids: list[str] = []
    for var, locs in sorted(required.items()):
        ev = evidence_store.add(
            source_type=SourceType.deterministic_check,
            source_path=locs[0].split(":")[0],
            summary=f"Required environment variable {var} referenced without a default",
            payload={"variable": var, "locations": locs, "documented": var in documented},
        )
        evidence_ids.append(ev.id)

    undocumented = sorted(v for v in required if v not in documented)

    if undocumented:
        return DeterministicCheckResult(
            check_id="DC-08",
            name="Required environment variable documentation",
            status=CheckStatus.fail,
            details=(
                f"Required environment variable(s) {undocumented} are read without a default "
                f"and are not documented in {', '.join(_DOC_FILES)}."
            ),
            evidence_ids=evidence_ids,
        )

    return DeterministicCheckResult(
        check_id="DC-08",
        name="Required environment variable documentation",
        status=CheckStatus.pass_,
        details=f"All required environment variable(s) {sorted(required)} are documented.",
        evidence_ids=evidence_ids,
    )
