from __future__ import annotations

from app.schemas.enums import (
    Decision,
    FindingCategory,
    Severity,
    SourceType,
    VerificationStatus,
)
from app.schemas.evidence import Evidence, content_hash_of
from app.schemas.findings import Finding
from app.schemas.integrity import validate_report_integrity
from app.schemas.report import AuditReport


def make_sample_report(
    *,
    run_id: str = "run-001",
    sha: str = "0123456789abcdef0123456789abcdef01234567",
    decision: Decision = Decision.GO,
) -> AuditReport:
    """Helper to build a clean baseline report with no violations."""
    ev = Evidence(
        id="E-001",
        audit_run_id=run_id,
        source_type=SourceType.github_file,
        source_path="pyproject.toml",
        source_ref=sha,
        content_hash=content_hash_of("dependencies"),
        summary="Valid dependencies evidence",
    )
    finding = Finding(
        id="F-001",
        audit_run_id=run_id,
        category=FindingCategory.dependencies,
        title="Minor version mismatch",
        severity=Severity.low,
        claim="Dependency pinned to old patch version",
        confidence=0.8,
        evidence_ids=["E-001"],
        recommended_action="Update dependency",
        verification_status=VerificationStatus.confirmed,
    )
    return AuditReport(
        audit_run_id=run_id,
        repository_url="https://github.com/example/repo",
        requested_ref="main",
        commit_sha=sha,
        mode="final",
        decision=decision,
        executive_summary="All checks clean.",
        findings=[finding],
        rejected_findings=[],
        verifications=[],
        evidence=[ev],
        deterministic_checks=[],
        limitations=[],
        runtime_ms=1200,
        model_id="claude-sonnet-5",
        prompt_version="p1",
        estimated_cost_usd=0.01,
    )


def test_clean_report_has_no_violations() -> None:
    report = make_sample_report()
    violations = validate_report_integrity(report)
    assert violations == []
    assert len(report.confirmed_blockers()) == 0
    ev_map = report.evidence_by_id()
    assert "E-001" in ev_map
    assert ev_map["E-001"].id == "E-001"


def test_violation_unsupported_critical() -> None:
    report = make_sample_report()
    crit_finding = Finding(
        id="F-002",
        audit_run_id=report.audit_run_id,
        category=FindingCategory.security,
        title="Critical vuln",
        severity=Severity.critical,
        claim="RCE in dependency",
        confidence=0.99,
        evidence_ids=[],
        recommended_action="Patch immediately",
        verification_status=VerificationStatus.confirmed,
    )
    report.findings.append(crit_finding)
    report.decision = Decision.NO_GO

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "UNSUPPORTED_CRITICAL" in codes
    crit_violation = next(v for v in violations if v.code == "UNSUPPORTED_CRITICAL")
    assert crit_violation.finding_id == "F-002"


def test_violation_dangling_evidence() -> None:
    report = make_sample_report()
    finding_with_dangling = Finding(
        id="F-003",
        audit_run_id=report.audit_run_id,
        category=FindingCategory.ci,
        title="CI timeout",
        severity=Severity.medium,
        claim="CI job took 2 hours",
        confidence=0.8,
        evidence_ids=["E-999"],
        recommended_action="Increase timeout",
        verification_status=VerificationStatus.confirmed,
    )
    report.findings.append(finding_with_dangling)

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "DANGLING_EVIDENCE" in codes
    dangling_violation = next(v for v in violations if v.code == "DANGLING_EVIDENCE")
    assert dangling_violation.finding_id == "F-003"
    assert dangling_violation.evidence_id == "E-999"


def test_violation_cross_run_evidence() -> None:
    report = make_sample_report()
    alien_evidence = Evidence(
        id="E-002",
        audit_run_id="other-run-999",
        source_type=SourceType.github_file,
        source_path="README.md",
        source_ref=report.commit_sha,
        content_hash=content_hash_of("readme"),
        summary="Alien evidence",
    )
    report.evidence.append(alien_evidence)

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "CROSS_RUN_EVIDENCE" in codes
    cross_violation = next(v for v in violations if v.code == "CROSS_RUN_EVIDENCE")
    assert cross_violation.evidence_id == "E-002"


def test_violation_stale_sha() -> None:
    report = make_sample_report()
    stale_evidence = Evidence(
        id="E-003",
        audit_run_id=report.audit_run_id,
        source_type=SourceType.github_file,
        source_path="README.md",
        source_ref="ffffffffffffffffffffffffffffffffffffffff",
        content_hash=content_hash_of("stale"),
        summary="Stale commit evidence",
    )
    report.evidence.append(stale_evidence)

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "STALE_SHA" in codes
    stale_violation = next(v for v in violations if v.code == "STALE_SHA")
    assert stale_violation.evidence_id == "E-003"


def test_violation_unverified_critical() -> None:
    report = make_sample_report()
    unverified_finding = Finding(
        id="F-004",
        audit_run_id=report.audit_run_id,
        category=FindingCategory.security,
        title="Unverified critical leak",
        severity=Severity.critical,
        claim="API key in git log",
        confidence=0.9,
        evidence_ids=["E-001"],
        recommended_action="Verify leak",
        verification_status=VerificationStatus.pending,
    )
    report.findings.append(unverified_finding)
    report.decision = Decision.NO_GO

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "UNVERIFIED_CRITICAL" in codes
    unverified_violation = next(v for v in violations if v.code == "UNVERIFIED_CRITICAL")
    assert unverified_violation.finding_id == "F-004"


def test_violation_duplicate_id() -> None:
    report = make_sample_report()
    dup_finding = Finding(
        id="F-001",
        audit_run_id=report.audit_run_id,
        category=FindingCategory.ci,
        title="Duplicate finding",
        severity=Severity.low,
        claim="Claim",
        confidence=0.5,
        evidence_ids=["E-001"],
        recommended_action="Action",
        verification_status=VerificationStatus.rejected,
    )
    report.rejected_findings.append(dup_finding)

    dup_evidence = Evidence(
        id="E-001",
        audit_run_id=report.audit_run_id,
        source_type=SourceType.github_file,
        source_path="other.py",
        source_ref=report.commit_sha,
        content_hash=content_hash_of("other"),
        summary="Duplicate evidence",
    )
    report.evidence.append(dup_evidence)

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert codes.count("DUPLICATE_ID") == 2


def test_violation_decision_policy_breach() -> None:
    report = make_sample_report(decision=Decision.GO)
    confirmed_critical = Finding(
        id="F-005",
        audit_run_id=report.audit_run_id,
        category=FindingCategory.security,
        title="Confirmed critical CVE",
        severity=Severity.critical,
        claim="Known critical remote code execution vulnerability",
        confidence=0.99,
        evidence_ids=["E-001"],
        recommended_action="Block release",
        verification_status=VerificationStatus.confirmed,
    )
    report.findings.append(confirmed_critical)

    violations = validate_report_integrity(report)
    codes = [v.code for v in violations]
    assert "DECISION_POLICY_BREACH" in codes
    breach_violation = next(v for v in violations if v.code == "DECISION_POLICY_BREACH")
    assert breach_violation.finding_id == "F-005"

    blockers = report.confirmed_blockers()
    assert len(blockers) == 1
    assert blockers[0].id == "F-005"
