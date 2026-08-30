# path: tests/test_score.py
import pytest

from app.schemas.enums import Decision, FindingCategory, Severity, SourceType
from app.schemas.evidence import Evidence
from app.schemas.findings import Finding
from app.schemas.report import AuditReport
from eval.score import CaseScore, aggregate, score_case


def make_sample_gold(
    case_id: str = "case_01",
    held_out: bool = False,
    expected_decision: str = "NO-GO",
    blockers: list[dict] | None = None,
    acceptable_extra: list[dict] | None = None,
    forbidden: list[dict] | None = None,
) -> dict:
    if blockers is None:
        blockers = [
            {
                "blocker_id": "b1_failing_tests",
                "severity": "critical",
                "category": "tests",
                "description": "Tests are failing",
                "match_any_of": [["unit", "test", "failed"], ["test", "broken"]],
                "acceptable_evidence": ["test_report.json"],
            }
        ]
    return {
        "case_id": case_id,
        "name": "Sample Test Case",
        "held_out": held_out,
        "requested_ref": "v1.0.0",
        "expected_decision": expected_decision,
        "blockers": blockers,
        "acceptable_extra_findings": acceptable_extra or [],
        "forbidden_findings": forbidden or [],
        "notes": "Testing notes",
    }


def make_sample_evidence(
    ev_id: str = "E-001",
    audit_run_id: str = "run_01",
    source_ref: str = "a" * 40,
    source_path: str = "test_report.json",
) -> Evidence:
    return Evidence(
        id=ev_id,
        audit_run_id=audit_run_id,
        source_type=SourceType.test_result,
        source_path=source_path,
        source_ref=source_ref,
        content_hash="sha256:" + "0" * 64,
        summary="Sample evidence summary",
        payload={},
    )


def make_sample_report(
    case_id: str = "case_01",
    commit_sha: str = "a" * 40,
    decision: Decision = Decision.NO_GO,
    findings: list[Finding] | None = None,
    evidence: list[Evidence] | None = None,
    runtime_ms: int = 1000,
    cost: float = 0.01,
) -> AuditReport:
    return AuditReport(
        audit_run_id=f"run_{case_id}",
        repository_url=f"https://github.com/org/{case_id}",
        requested_ref="v1.0.0",
        commit_sha=commit_sha,
        mode="baseline",
        decision=decision,
        executive_summary="Executive summary test",
        findings=findings or [],
        evidence=evidence or [],
        runtime_ms=runtime_ms,
        model_id="gemini-2.5-flash",
        prompt_version="p1",
        estimated_cost_usd=cost,
    )


def test_blocker_detected_when_matching_finding_present() -> None:
    gold = make_sample_gold()
    finding = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test failed on main",
        claim="The unit test suite broke on auth endpoint.",
        confidence=0.9,
        evidence_ids=["E-001"],
        recommended_action="Fix test",
    )
    ev = make_sample_evidence("E-001", source_ref="a" * 40)
    report = make_sample_report(findings=[finding], evidence=[ev])

    score = score_case(report, gold)
    assert score.matched_blockers == ["b1_failing_tests"]
    assert score.missed_blockers == []
    assert score.false_positives == []
    assert score.blockers_total == 1

    agg = aggregate([score])
    assert agg["all"]["cbr"] == 1.0
    assert agg["all"]["precision"] == 1.0
    assert agg["all"]["f1"] == 1.0


def test_blocker_missed_when_no_matching_finding() -> None:
    gold = make_sample_gold()
    finding = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.docs,
        severity=Severity.critical,
        title="Docs missing link",
        claim="Missing documentation link in readme.",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Add docs",
    )
    report = make_sample_report(findings=[finding])

    score = score_case(report, gold)
    assert score.matched_blockers == []
    assert score.missed_blockers == ["b1_failing_tests"]
    assert "F-001" in score.false_positives

    agg = aggregate([score])
    assert agg["all"]["cbr"] == 0.0
    assert agg["all"]["precision"] == 0.0


def test_one_finding_cannot_close_two_blockers() -> None:
    blockers = [
        {
            "blocker_id": "b1_test_failure",
            "severity": "critical",
            "category": "tests",
            "description": "Test failure",
            "match_any_of": [["unit", "test"]],
            "acceptable_evidence": [],
        },
        {
            "blocker_id": "b2_integration_test_failure",
            "severity": "critical",
            "category": "tests",
            "description": "Integration test failure",
            "match_any_of": [["unit", "test"]],
            "acceptable_evidence": [],
        },
    ]
    gold = make_sample_gold(blockers=blockers)
    finding = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test broken",
        claim="A unit test is failing in CI.",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(findings=[finding])

    score = score_case(report, gold)
    assert len(score.matched_blockers) == 1
    assert score.matched_blockers == ["b1_test_failure"]
    assert score.missed_blockers == ["b2_integration_test_failure"]
    assert score.false_positives == []

    agg = aggregate([score])
    assert agg["all"]["cbr"] == 0.5


def test_matching_picks_higher_confidence_finding() -> None:
    gold = make_sample_gold()
    f1_low_conf = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test failed low conf",
        claim="unit test failed claim",
        confidence=0.6,
        evidence_ids=[],
        recommended_action="Fix",
    )
    f2_high_conf = Finding(
        id="F-002",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test failed high conf",
        claim="unit test failed claim",
        confidence=0.95,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(findings=[f1_low_conf, f2_high_conf])

    score = score_case(report, gold)
    assert score.matched_blockers == ["b1_failing_tests"]
    assert score.false_positives == ["F-001"]


def test_matching_picks_smaller_numeric_f_id_on_confidence_tie() -> None:
    gold = make_sample_gold()
    f1_smaller_id = Finding(
        id="F-003",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test failed",
        claim="unit test failed claim",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix",
    )
    f2_larger_id = Finding(
        id="F-015",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Unit test failed",
        claim="unit test failed claim",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(findings=[f2_larger_id, f1_smaller_id])

    score = score_case(report, gold)
    assert score.matched_blockers == ["b1_failing_tests"]
    assert score.false_positives == ["F-015"]


def test_critical_or_high_finding_without_match_becomes_false_positive() -> None:
    gold = make_sample_gold(blockers=[])
    f_crit = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.security,
        severity=Severity.critical,
        title="Critical vuln",
        claim="Vulnerability found",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Patch",
    )
    f_high = Finding(
        id="F-002",
        audit_run_id="run_01",
        category=FindingCategory.ci,
        severity=Severity.high,
        title="CI missing",
        claim="CI workflow missing",
        confidence=0.8,
        evidence_ids=[],
        recommended_action="Add CI",
    )
    report = make_sample_report(findings=[f_crit, f_high])

    score = score_case(report, gold)
    assert sorted(score.false_positives) == ["F-001", "F-002"]


def test_finding_matching_acceptable_extra_is_not_false_positive() -> None:
    gold = make_sample_gold(
        blockers=[],
        acceptable_extra=[
            {
                "category": "docs",
                "match_any_of": [["license", "missing"]],
                "note": "Acceptable docs note",
            }
        ],
    )
    f_extra = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.docs,
        severity=Severity.high,
        title="License missing from repo",
        claim="License file is missing in project root.",
        confidence=0.85,
        evidence_ids=[],
        recommended_action="Add license",
    )
    report = make_sample_report(findings=[f_extra])

    score = score_case(report, gold)
    assert score.false_positives == []


def test_medium_low_info_findings_excluded_from_false_positives() -> None:
    gold = make_sample_gold(blockers=[])
    f_med = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.docs,
        severity=Severity.medium,
        title="Typo in docs",
        claim="Minor typo",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix typo",
    )
    f_low = Finding(
        id="F-002",
        audit_run_id="run_01",
        category=FindingCategory.config,
        severity=Severity.low,
        title="Unused config",
        claim="Config option unused",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Clean config",
    )
    f_info = Finding(
        id="F-003",
        audit_run_id="run_01",
        category=FindingCategory.other,
        severity=Severity.info,
        title="Informational",
        claim="Just info",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Note",
    )
    report = make_sample_report(findings=[f_med, f_low, f_info])

    score = score_case(report, gold)
    assert score.false_positives == []


def test_trap_hit_counted_and_remains_false_positive() -> None:
    gold = make_sample_gold(
        blockers=[],
        forbidden=[
            {
                "match_any_of": [["tests", "missing"], ["no", "tests"]],
                "note": "Tests exist, do not claim they are missing",
            }
        ],
    )
    f_trap = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Tests missing in repository",
        claim="There are no tests present.",
        confidence=0.99,
        evidence_ids=[],
        recommended_action="Add tests",
    )
    report = make_sample_report(findings=[f_trap])

    score = score_case(report, gold)
    assert score.trap_hits == 1
    assert "F-001" in score.false_positives


def test_evidence_referencing_nonexistent_evidence_not_covered() -> None:
    gold = make_sample_gold(blockers=[])
    f = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.info,
        title="Test info",
        claim="Test info claim",
        confidence=0.5,
        evidence_ids=["E-999"],
        recommended_action="None",
    )
    report = make_sample_report(findings=[f], evidence=[])

    score = score_case(report, gold)
    assert score.evidence_coverage == 0.0


def test_evidence_with_mismatched_source_ref_not_covered() -> None:
    gold = make_sample_gold(blockers=[])
    f = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.info,
        title="Test info",
        claim="Test info claim",
        confidence=0.5,
        evidence_ids=["E-001"],
        recommended_action="None",
    )
    ev_foreign = make_sample_evidence("E-001", source_ref="b" * 40)
    report = make_sample_report(commit_sha="a" * 40, findings=[f], evidence=[ev_foreign])

    score = score_case(report, gold)
    assert score.evidence_coverage == 0.0


def test_critical_finding_with_empty_evidence_ids_increases_unsupported_critical() -> None:
    gold = make_sample_gold(blockers=[])
    f_crit = Finding(
        id="F-001",
        audit_run_id="run_01",
        category=FindingCategory.security,
        severity=Severity.critical,
        title="Unsupported critical blocker",
        claim="Claim with zero evidence attached",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(findings=[f_crit])

    score = score_case(report, gold)
    assert score.unsupported_critical == 1
    assert score.critical_evidence_coverage == 0.0


def test_failed_case_behavior_and_denominators() -> None:
    gold = make_sample_gold(
        expected_decision="NO-GO",
        blockers=[
            {
                "blocker_id": "b1_critical",
                "severity": "critical",
                "category": "tests",
                "description": "desc",
                "match_any_of": [["broken"]],
                "acceptable_evidence": [],
            }
        ],
    )
    report = make_sample_report(decision=Decision.REVIEW)

    score = score_case(report, gold, run_status="failed")
    assert score.status == "failed"
    assert score.matched_blockers == []
    assert score.missed_blockers == ["b1_critical"]
    assert score.blockers_total == 1

    agg = aggregate([score])
    assert agg["all"]["cbr"] == 0.0
    assert agg["all"]["decision_accuracy"] == 0.0
    assert agg["all"]["successful_run_rate"] == 0.0


def test_failed_run_with_partial_report_still_scores_false_positives() -> None:
    # A failed run whose partial report already fabricated an unsupported
    # critical finding (no evidence_ids at all) must not look "clean" just
    # because the run crashed afterwards.
    gold = make_sample_gold(
        expected_decision="NO-GO",
        blockers=[
            {
                "blocker_id": "b1_critical",
                "severity": "critical",
                "category": "tests",
                "description": "desc",
                "match_any_of": [["broken"]],
                "acceptable_evidence": [],
            }
        ],
    )
    fabricated = Finding(
        id="F-999",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Hallucinated critical blocker",
        claim="Something totally unrelated to any gold blocker or forbidden finding.",
        confidence=0.95,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(decision=Decision.NO_GO, findings=[fabricated])

    score = score_case(report, gold, run_status="failed")

    assert score.status == "failed"
    # Recall side still follows failed-run policy.
    assert score.matched_blockers == []
    assert score.missed_blockers == ["b1_critical"]
    # Precision side must reflect the partial report's actual bad behavior.
    assert score.false_positives == ["F-999"]
    assert score.unsupported_critical == 1

    agg = aggregate([score])
    assert agg["all"]["unsupported_critical_total"] == 1


def test_failed_run_with_partial_report_still_scores_trap_hits() -> None:
    gold = make_sample_gold(
        expected_decision="NO-GO",
        forbidden=[{"description": "Do not flag renamed files as risky", "match_any_of": [["rename", "risk"]]}],
    )
    trap_finding = Finding(
        id="F-888",
        audit_run_id="run_01",
        category=FindingCategory.tests,
        severity=Severity.critical,
        title="Renamed file introduces risk",
        claim="A rename was detected and treated as risk.",
        confidence=0.9,
        evidence_ids=[],
        recommended_action="Fix",
    )
    report = make_sample_report(decision=Decision.NO_GO, findings=[trap_finding])

    score = score_case(report, gold, run_status="failed")

    assert score.status == "failed"
    assert score.trap_hits == 1


def test_micro_aggregation_cbr_formula() -> None:
    # Case 1: 1 critical blocker, 1 detected (1/1)
    gold1 = make_sample_gold(case_id="case_01", held_out=False, blockers=[
        {"blocker_id": "b1", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["critone"]], "acceptable_evidence": []}
    ])
    f1 = Finding(id="F-001", audit_run_id="r1", category=FindingCategory.tests, severity=Severity.critical, title="critone found", claim="critone", confidence=1.0, evidence_ids=[], recommended_action="")
    r1 = make_sample_report(case_id="case_01", findings=[f1])
    s1 = score_case(r1, gold1)

    # Case 2: 3 critical blockers, 1 detected (1/3)
    gold2 = make_sample_gold(case_id="case_02", held_out=False, blockers=[
        {"blocker_id": "b2_1", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["crittwo"]], "acceptable_evidence": []},
        {"blocker_id": "b2_2", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["critthree"]], "acceptable_evidence": []},
        {"blocker_id": "b2_3", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["critfour"]], "acceptable_evidence": []},
    ])
    f2 = Finding(id="F-001", audit_run_id="r2", category=FindingCategory.tests, severity=Severity.critical, title="crittwo found", claim="crittwo", confidence=1.0, evidence_ids=[], recommended_action="")
    r2 = make_sample_report(case_id="case_02", findings=[f2])
    s2 = score_case(r2, gold2)

    # Micro average: (1 + 1) / (1 + 3) = 2/4 = 0.5
    agg = aggregate([s1, s2])
    assert agg["development"]["cbr"] == 0.5
    assert agg["all"]["cbr"] == 0.5


def test_division_by_zero_returns_zero_in_all_metrics() -> None:
    agg_empty = aggregate([])
    for slice_name in ("development", "held_out", "all"):
        data = agg_empty[slice_name]
        assert data["cbr"] == 0.0
        assert data["high_blocker_recall"] == 0.0
        assert data["precision"] == 0.0
        assert data["f1"] == 0.0
        assert data["decision_accuracy"] == 0.0
        assert data["evidence_coverage"] == 0.0
        assert data["critical_evidence_coverage"] == 0.0
        assert data["successful_run_rate"] == 0.0
        assert data["total_runtime_ms"] == 0
        assert data["total_cost"] == 0.0


def test_held_out_slice_separation() -> None:
    # Case 01: dev case
    gold_dev = make_sample_gold(case_id="case_01", held_out=False, blockers=[
        {"blocker_id": "b_dev", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["devblocker"]], "acceptable_evidence": []}
    ])
    f_dev = Finding(id="F-001", audit_run_id="r1", category=FindingCategory.tests, severity=Severity.critical, title="devblocker", claim="claim", confidence=1.0, evidence_ids=[], recommended_action="")
    s_dev = score_case(make_sample_report(case_id="case_01", findings=[f_dev]), gold_dev)

    # Case 09: held-out case
    gold_held = make_sample_gold(case_id="case_09", held_out=True, blockers=[
        {"blocker_id": "b_held", "severity": "critical", "category": "tests", "description": "", "match_any_of": [["heldblocker"]], "acceptable_evidence": []}
    ])
    s_held = score_case(make_sample_report(case_id="case_09", findings=[]), gold_held)

    agg = aggregate([s_dev, s_held])
    assert agg["development"]["cbr"] == 1.0
    assert agg["held_out"]["cbr"] == 0.0
    assert agg["all"]["cbr"] == 0.5
