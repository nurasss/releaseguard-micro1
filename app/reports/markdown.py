# path: app/reports/markdown.py
"""Per-audit Markdown report renderer (ТЗ §14 — all 17 required sections)."""
from __future__ import annotations

from app.schemas.enums import CheckStatus, Severity, VerificationStatus
from app.security.redaction import redact
from app.schemas.findings import Finding
from app.schemas.report import AuditReport


def _confirmed_critical(report: AuditReport) -> list[Finding]:
    return [
        f
        for f in report.findings
        if f.severity == Severity.critical and f.verification_status == VerificationStatus.confirmed
    ]


def _confirmed_high(report: AuditReport) -> list[Finding]:
    return [
        f
        for f in report.findings
        if f.severity == Severity.high and f.verification_status == VerificationStatus.confirmed
    ]


def _uncertain_findings(report: AuditReport) -> list[Finding]:
    return [f for f in report.findings if f.verification_status == VerificationStatus.needs_human_review]


def _render_evidence_block(report: AuditReport, finding: Finding) -> str:
    evidence_by_id = report.evidence_by_id()
    lines = []
    for eid in finding.evidence_ids:
        ev = evidence_by_id.get(eid)
        if ev is None:
            lines.append(f"{eid} — (evidence not resolvable in this report)")
            continue
        location = ev.source_path
        if ev.line_start is not None and ev.line_end is not None:
            location += f":{ev.line_start}-{ev.line_end}"
        lines.append(f"{eid} — {redact(location)} — {redact(ev.summary)}")
    return "\n".join(lines) if lines else "(no evidence cited)"


def _render_finding_block(report: AuditReport, finding: Finding) -> str:
    verification = finding.verification_status.value if hasattr(finding.verification_status, "value") else str(finding.verification_status)
    return (
        f"### {finding.id} — {finding.severity.value.upper()}\n"
        f"{redact(finding.claim)}\n\n"
        f"Evidence:\n{_render_evidence_block(report, finding)}\n\n"
        f"Verification: {verification.upper()}\n"
        f"Confidence: {finding.confidence:.2f}\n\n"
        f"Recommended action:\n{redact(finding.recommended_action)}\n"
    )


def render_report_md(report: AuditReport) -> str:
    """Render a single AuditReport into the Markdown format required by ТЗ §14."""
    confirmed_critical = _confirmed_critical(report)
    confirmed_high = _confirmed_high(report)
    uncertain = _uncertain_findings(report)

    lines: list[str] = []
    lines.append("# ReleaseGuard Audit")
    lines.append("")
    # 1-4: repository, ref, commit, overall status
    lines.append(f"Repository: {redact(report.repository_url)}")
    lines.append(f"Requested ref: {report.requested_ref}")
    lines.append(f"Commit: {report.commit_sha}")
    lines.append(f"Decision: {report.decision.value}")
    lines.append("")

    # 5: executive summary
    lines.append("## Executive summary")
    lines.append("")
    lines.append(redact(report.executive_summary) or "(none provided)")
    lines.append("")

    # 6: confirmed blockers
    lines.append("## Confirmed blockers")
    lines.append("")
    if confirmed_critical:
        for f in confirmed_critical:
            lines.append(_render_finding_block(report, f))
    else:
        lines.append("None.")
    lines.append("")

    # 7: high-risk warnings
    lines.append("## High-risk warnings")
    lines.append("")
    if confirmed_high:
        for f in confirmed_high:
            lines.append(_render_finding_block(report, f))
    else:
        lines.append("None.")
    lines.append("")

    # 8: uncertain findings
    lines.append("## Uncertain findings (needs human review)")
    lines.append("")
    if uncertain:
        for f in uncertain:
            lines.append(_render_finding_block(report, f))
    else:
        lines.append("None.")
    lines.append("")

    # 9: passed deterministic checks (plus other statuses, for completeness)
    lines.append("## Deterministic checks")
    lines.append("")
    if report.deterministic_checks:
        passed = [c for c in report.deterministic_checks if c.status == CheckStatus.pass_]
        others = [c for c in report.deterministic_checks if c.status != CheckStatus.pass_]
        lines.append("Passed:")
        if passed:
            for c in passed:
                lines.append(f"- {c.check_id} {redact(c.name)}: {redact(c.details)}")
        else:
            lines.append("- None.")
        if others:
            lines.append("")
            lines.append("Other results:")
            for c in others:
                status_val = c.status.value if hasattr(c.status, "value") else str(c.status)
                lines.append(f"- {c.check_id} {redact(c.name)} [{status_val}]: {redact(c.details)}")
    else:
        lines.append("No deterministic checks were run for this mode.")
    lines.append("")

    # 10: evidence per finding — already inline in each finding block above (sections 6-8);
    # for findings not in those sections (e.g. medium/low/info, or pending) list evidence too.
    other_findings = [
        f
        for f in report.findings
        if f not in confirmed_critical and f not in confirmed_high and f not in uncertain
    ]
    lines.append("## Other findings")
    lines.append("")
    if other_findings:
        for f in other_findings:
            lines.append(_render_finding_block(report, f))
    else:
        lines.append("None.")
    lines.append("")

    # 11: findings rejected by Verifier / evidence enforcement
    lines.append("## Findings rejected by Verifier")
    lines.append("")
    if report.rejected_findings:
        for f in report.rejected_findings:
            lines.append(_render_finding_block(report, f))
    else:
        lines.append("None.")
    lines.append("")

    # 12: recommended human actions
    lines.append("## Recommended human actions")
    lines.append("")
    actionable = confirmed_critical + confirmed_high + uncertain
    if actionable:
        for f in actionable:
            lines.append(f"- {f.id}: {redact(f.recommended_action)}")
    else:
        lines.append("None required.")
    lines.append("")

    # 13: limitations
    lines.append("## Limitations")
    lines.append("")
    if report.limitations:
        for lim in report.limitations:
            lines.append(f"- {redact(lim)}")
    else:
        lines.append("None noted.")
    lines.append("")

    # 14-17: runtime, model, prompt version, cost
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"Runtime: {report.runtime_ms} ms")
    lines.append(f"Model: {report.model_id}")
    lines.append(f"Prompt version: {report.prompt_version}")
    lines.append(f"Estimated LLM cost: ${report.estimated_cost_usd:.4f}")
    lines.append("")

    return "\n".join(lines)
