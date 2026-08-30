# path: tests/test_decision_policy.py
from app.policy.decision import decide
from app.schemas.enums import Decision, FindingCategory, Severity, VerificationStatus
from app.schemas.findings import Finding


def make_finding(
    severity: Severity,
    verification_status: VerificationStatus,
    evidence_ids: list[str] | None = None,
    fid: str = "F-001",
) -> Finding:
    return Finding(
        id=fid,
        audit_run_id="run_01",
        category=FindingCategory.ci,
        title="Sample finding",
        severity=severity,
        claim="Sample claim",
        confidence=0.9,
        evidence_ids=evidence_ids if evidence_ids is not None else ["E-001"],
        recommended_action="Fix it",
        verification_status=verification_status,
    )


def test_no_findings_is_go() -> None:
    assert decide([]) == Decision.GO


def test_confirmed_critical_is_no_go() -> None:
    f = make_finding(Severity.critical, VerificationStatus.confirmed)
    assert decide([f]) == Decision.NO_GO


def test_confirmed_high_without_critical_is_review() -> None:
    f = make_finding(Severity.high, VerificationStatus.confirmed)
    assert decide([f]) == Decision.REVIEW


def test_pending_critical_without_confirmation_is_review() -> None:
    f = make_finding(Severity.critical, VerificationStatus.pending)
    assert decide([f]) == Decision.REVIEW


def test_needs_human_review_high_is_review() -> None:
    f = make_finding(Severity.high, VerificationStatus.needs_human_review)
    assert decide([f]) == Decision.REVIEW


def test_high_without_evidence_is_review() -> None:
    f = make_finding(Severity.high, VerificationStatus.confirmed, evidence_ids=[])
    assert decide([f]) == Decision.REVIEW


def test_only_low_severity_findings_is_go() -> None:
    f = make_finding(Severity.low, VerificationStatus.pending)
    assert decide([f]) == Decision.GO


def test_confirmed_critical_wins_over_other_review_signals() -> None:
    critical = make_finding(Severity.critical, VerificationStatus.confirmed, fid="F-001")
    high = make_finding(Severity.high, VerificationStatus.needs_human_review, fid="F-002")
    assert decide([critical, high]) == Decision.NO_GO
