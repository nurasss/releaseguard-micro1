# path: app/policy/decision.py
"""Decision Policy (ТЗ §13) — deterministic, no LLM call.

Operates on the findings that survive verification (rejected findings must
already have been moved out of this list into report.rejected_findings by the
caller — see app/orchestration/runner.py).
"""
from __future__ import annotations

from app.schemas.enums import Decision, Severity, VerificationStatus
from app.schemas.findings import Finding


def decide(findings: list[Finding]) -> Decision:
    """Apply the ReleaseGuard Decision Policy to a set of surviving findings.

    NO-GO:   at least one confirmed critical finding.
    REVIEW:  no confirmed critical, but there is a confirmed high finding,
             or an unverified/uncertain high-or-critical finding, or a
             high/critical finding without evidence (insufficient evidence).
    GO:      otherwise.
    """
    has_confirmed_critical = any(
        f.severity == Severity.critical and f.verification_status == VerificationStatus.confirmed
        for f in findings
    )
    if has_confirmed_critical:
        return Decision.NO_GO

    has_confirmed_high = any(
        f.severity == Severity.high and f.verification_status == VerificationStatus.confirmed
        for f in findings
    )
    has_unresolved_high_risk = any(
        f.severity in (Severity.critical, Severity.high)
        and f.verification_status in (VerificationStatus.pending, VerificationStatus.needs_human_review)
        for f in findings
    )
    has_insufficient_evidence = any(
        f.severity in (Severity.critical, Severity.high) and not f.evidence_ids
        for f in findings
    )

    if has_confirmed_high or has_unresolved_high_risk or has_insufficient_evidence:
        return Decision.REVIEW

    return Decision.GO
