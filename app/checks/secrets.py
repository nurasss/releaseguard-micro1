# path: app/checks/secrets.py
"""DC-10: simple secret scan over readable text files.

Reuses the pattern list already used to redact secrets from trajectory logs
(app.security.redaction) rather than maintaining a second copy.
"""

from __future__ import annotations

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.security.redaction import find_secrets
from app.sources.base import RepositorySource, ResolvedRef

_MAX_FILE_BYTES = 300_000
_SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}


def check_secret_scan(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    tree = source.get_tree()
    findings: list[dict] = []
    scanned = 0

    for entry in tree:
        if entry.size_bytes > _MAX_FILE_BYTES:
            continue
        suffix = "." + entry.path.rsplit(".", 1)[-1].lower() if "." in entry.path else ""
        if suffix in _SKIP_SUFFIXES:
            continue
        try:
            content = source.read_file(entry.path).content
        except Exception:
            continue
        scanned += 1
        for line_no, pattern_name, masked in find_secrets(content):
            findings.append(
                {"path": entry.path, "line": line_no, "pattern": pattern_name, "masked": masked}
            )

    evidence_ids: list[str] = []

    if findings:
        for f in findings:
            ev = evidence_store.add(
                source_type=SourceType.deterministic_check,
                source_path=f["path"],
                summary=f"Potential secret detected: {f['pattern']}",
                payload=f,
                line_start=f["line"],
                line_end=f["line"],
            )
            evidence_ids.append(ev.id)

        affected_files = sorted({f["path"] for f in findings})
        pattern_names = sorted({f["pattern"] for f in findings})
        return DeterministicCheckResult(
            check_id="DC-10",
            name="Secret scan",
            status=CheckStatus.fail,
            details=(
                f"Detected {len(findings)} potential secret pattern match(es) "
                f"({', '.join(pattern_names)}) across {len(affected_files)} file(s): "
                f"{affected_files}."
            ),
            evidence_ids=evidence_ids,
        )

    ev = evidence_store.add(
        source_type=SourceType.deterministic_check,
        source_path="<repository tree>",
        summary=f"No secret patterns detected across {scanned} scanned file(s)",
        payload={"files_scanned": scanned},
    )
    return DeterministicCheckResult(
        check_id="DC-10",
        name="Secret scan",
        status=CheckStatus.pass_,
        details=f"No known secret patterns detected across {scanned} scanned text file(s).",
        evidence_ids=[ev.id],
    )
