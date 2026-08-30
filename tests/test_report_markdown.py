# path: tests/test_report_markdown.py
from app.reports.markdown import render_report_md
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, Decision, FindingCategory, Severity, VerificationStatus
from app.schemas.evidence import Evidence
from app.schemas.findings import Finding
from app.schemas.report import AuditReport


def make_evidence(eid: str = "E-001") -> Evidence:
    return Evidence(
        id=eid,
        audit_run_id="aud_001",
        source_type="github_file",
        source_path=".github/workflows/release.yml",
        source_ref="a" * 40,
        line_start=17,
        line_end=24,
        content_hash="sha256:" + "0" * 64,
        summary="Release workflow is triggered only on main",
        payload={},
    )


def make_finding(
    fid: str = "F-001",
    severity: Severity = Severity.critical,
    verification_status: VerificationStatus = VerificationStatus.confirmed,
    evidence_ids: list[str] | None = None,
) -> Finding:
    return Finding(
        id=fid,
        audit_run_id="aud_001",
        category=FindingCategory.ci,
        title="Release workflow does not run for release branch",
        severity=severity,
        claim="The repository's release CI does not execute on the configured release branch.",
        confidence=0.92,
        evidence_ids=evidence_ids if evidence_ids is not None else ["E-001"],
        recommended_action="Update workflow trigger and validate it before release.",
        verification_status=verification_status,
    )


def make_report(**overrides) -> AuditReport:
    defaults = dict(
        audit_run_id="aud_001",
        repository_url="https://github.com/org/project",
        requested_ref="v1.4.0",
        commit_sha="a" * 40,
        mode="final",
        decision=Decision.NO_GO,
        executive_summary="Release is blocked by a confirmed CI trigger issue.",
        findings=[make_finding()],
        rejected_findings=[],
        verifications=[],
        evidence=[make_evidence()],
        deterministic_checks=[
            DeterministicCheckResult(
                check_id="DC-02", name="CI presence", status=CheckStatus.pass_, details="Workflow found."
            )
        ],
        limitations=[],
        runtime_ms=1500,
        model_id="gemini-2.5-flash",
        prompt_version="p1",
        estimated_cost_usd=0.01,
    )
    defaults.update(overrides)
    return AuditReport(**defaults)


def test_render_includes_all_required_sections() -> None:
    report = make_report()
    md = render_report_md(report)

    assert "Repository: https://github.com/org/project" in md
    assert "Requested ref: v1.4.0" in md
    assert f"Commit: {'a' * 40}" in md
    assert "Decision: NO-GO" in md
    assert "## Executive summary" in md
    assert "## Confirmed blockers" in md
    assert "F-001" in md
    assert "## High-risk warnings" in md
    assert "## Uncertain findings" in md
    assert "## Deterministic checks" in md
    assert "DC-02" in md
    assert "## Findings rejected by Verifier" in md
    assert "## Recommended human actions" in md
    assert "## Limitations" in md
    assert "Runtime: 1500 ms" in md
    assert "Model: gemini-2.5-flash" in md
    assert "Prompt version: p1" in md
    assert "Estimated LLM cost: $0.0100" in md
    assert "E-001" in md
    assert ".github/workflows/release.yml:17-24" in md


def test_confirmed_critical_appears_only_in_confirmed_blockers_section() -> None:
    report = make_report()
    md = render_report_md(report)
    confirmed_section = md.split("## High-risk warnings")[0]
    assert "F-001" in confirmed_section


def test_uncertain_finding_appears_in_uncertain_section() -> None:
    finding = make_finding(verification_status=VerificationStatus.needs_human_review)
    report = make_report(findings=[finding], decision=Decision.REVIEW)
    md = render_report_md(report)
    uncertain_section = md.split("## Uncertain findings")[1].split("## Deterministic checks")[0]
    assert "F-001" in uncertain_section


def test_rejected_findings_render_in_their_own_section() -> None:
    rejected = make_finding(verification_status=VerificationStatus.rejected)
    report = make_report(findings=[], rejected_findings=[rejected], decision=Decision.GO)
    md = render_report_md(report)
    rejected_section = md.split("## Findings rejected by Verifier")[1].split("## Recommended human actions")[0]
    assert "F-001" in rejected_section


def test_no_findings_renders_none_placeholders() -> None:
    report = make_report(findings=[], decision=Decision.GO)
    md = render_report_md(report)
    assert "## Confirmed blockers" in md
    assert md.count("None.") >= 1
