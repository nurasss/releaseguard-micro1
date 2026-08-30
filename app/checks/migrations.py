# path: app/checks/migrations.py
"""DC-09: migration artifact indicators and whether release/deploy documentation
or workflows mention executing them.
"""

from __future__ import annotations

import re

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

_MIGRATION_KEYWORD_RE = re.compile(r"migrat", re.IGNORECASE)
_RELEASE_DOC_KEYWORDS = ("release", "deploy", "changelog")


def _is_migration_path(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.startswith("migrations/")
        or "/migrations/" in lowered
        or lowered.startswith("alembic/versions/")
        or "/alembic/versions/" in lowered
    )


def check_migration_execution(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    tree = source.get_tree()
    migration_files = sorted(e.path for e in tree if _is_migration_path(e.path))

    if not migration_files:
        return DeterministicCheckResult(
            check_id="DC-09",
            name="Migration execution coverage",
            status=CheckStatus.not_applicable,
            details="No migration directory or migration files found in repository.",
            evidence_ids=[],
        )

    ev = evidence_store.add(
        source_type=SourceType.deterministic_check,
        source_path="<repository tree>",
        summary=f"Found {len(migration_files)} migration file(s)",
        payload={"migration_files": migration_files},
    )
    evidence_ids = [ev.id]

    tree_paths = {e.path for e in tree}
    candidate_docs = {p for p in tree_paths if p == "README.md" or "RELEASE" in p.upper()}
    for wf in source.get_workflow_files():
        if any(k in wf.lower() for k in _RELEASE_DOC_KEYWORDS) or "deploy" in wf.lower():
            candidate_docs.add(wf)

    mentions: list[str] = []
    for doc_path in sorted(candidate_docs):
        try:
            content = source.read_file(doc_path).content
        except Exception:
            continue
        if _MIGRATION_KEYWORD_RE.search(content):
            mentions.append(doc_path)
            ev2 = evidence_store.add(
                source_type=SourceType.deterministic_check,
                source_path=doc_path,
                summary=f"{doc_path} mentions running migrations",
                payload={"path": doc_path},
                content=content,
            )
            evidence_ids.append(ev2.id)

    if mentions:
        return DeterministicCheckResult(
            check_id="DC-09",
            name="Migration execution coverage",
            status=CheckStatus.pass_,
            details=(
                f"Migration file(s) present ({len(migration_files)}) and release/deploy "
                f"documentation {mentions} reference running migrations."
            ),
            evidence_ids=evidence_ids,
        )

    return DeterministicCheckResult(
        check_id="DC-09",
        name="Migration execution coverage",
        status=CheckStatus.fail,
        details=(
            f"Migration file(s) present ({migration_files}) but no release/deploy "
            f"documentation or workflow among {sorted(candidate_docs)} mentions executing "
            "migrations."
        ),
        evidence_ids=evidence_ids,
    )
