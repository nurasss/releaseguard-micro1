from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import Decision, Severity, VerificationStatus
from app.schemas.report import AuditReport


class IntegrityViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    finding_id: str | None = None
    evidence_id: str | None = None
    message: str


def validate_report_integrity(report: AuditReport) -> list[IntegrityViolation]:
    """Validate report integrity and return a list of violations without throwing exceptions."""
    violations: list[IntegrityViolation] = []
    all_findings = report.findings + report.rejected_findings

    seen_finding_ids: set[str] = set()
    for finding in all_findings:
        if finding.id in seen_finding_ids:
            violations.append(
                IntegrityViolation(
                    code="DUPLICATE_ID",
                    finding_id=finding.id,
                    message=f"Duplicate finding ID {finding.id} detected.",
                )
            )
        else:
            seen_finding_ids.add(finding.id)

    seen_evidence_ids: set[str] = set()
    for ev in report.evidence:
        if ev.id in seen_evidence_ids:
            violations.append(
                IntegrityViolation(
                    code="DUPLICATE_ID",
                    evidence_id=ev.id,
                    message=f"Duplicate evidence ID {ev.id} detected.",
                )
            )
        else:
            seen_evidence_ids.add(ev.id)

    for ev in report.evidence:
        if ev.audit_run_id != report.audit_run_id:
            violations.append(
                IntegrityViolation(
                    code="CROSS_RUN_EVIDENCE",
                    evidence_id=ev.id,
                    message=(
                        f"Evidence {ev.id} audit_run_id {ev.audit_run_id} "
                        f"does not match report audit_run_id {report.audit_run_id}."
                    ),
                )
            )
        if ev.source_ref != report.commit_sha:
            violations.append(
                IntegrityViolation(
                    code="STALE_SHA",
                    evidence_id=ev.id,
                    message=(
                        f"Evidence {ev.id} source_ref {ev.source_ref} "
                        f"does not match report commit_sha {report.commit_sha}."
                    ),
                )
            )

    valid_evidence_ids = {e.id for e in report.evidence}
    for finding in all_findings:
        if finding.severity in (Severity.critical, Severity.high) and not finding.evidence_ids:
            violations.append(
                IntegrityViolation(
                    code="UNSUPPORTED_CRITICAL",
                    finding_id=finding.id,
                    message=(
                        f"Finding {finding.id} with severity {finding.severity.value} "
                        f"has no supporting evidence IDs."
                    ),
                )
            )
        for ev_id in finding.evidence_ids:
            if ev_id not in valid_evidence_ids:
                violations.append(
                    IntegrityViolation(
                        code="DANGLING_EVIDENCE",
                        finding_id=finding.id,
                        evidence_id=ev_id,
                        message=(
                            f"Finding {finding.id} references missing evidence ID {ev_id}."
                        ),
                    )
                )

    for finding in report.findings:
        if (
            finding.severity in (Severity.critical, Severity.high)
            and finding.verification_status == VerificationStatus.pending
        ):
            violations.append(
                IntegrityViolation(
                    code="UNVERIFIED_CRITICAL",
                    finding_id=finding.id,
                    message=(
                        f"Finding {finding.id} with severity {finding.severity.value} "
                        f"in report.findings has pending verification status."
                    ),
                )
            )

    if report.decision == Decision.GO:
        for finding in report.findings:
            if (
                finding.severity in (Severity.critical, Severity.high)
                and finding.verification_status == VerificationStatus.confirmed
            ):
                violations.append(
                    IntegrityViolation(
                        code="DECISION_POLICY_BREACH",
                        finding_id=finding.id,
                        message=(
                            f"Decision is GO despite confirmed finding {finding.id} "
                            f"with severity {finding.severity.value}."
                        ),
                    )
                )

    return violations
