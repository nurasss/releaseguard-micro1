# path: eval/score.py
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.schemas.enums import Severity
from app.schemas.findings import Finding
from app.schemas.report import AuditReport
from eval.validate_gold import finding_matches_blocker, keyword_set_matches


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="ignore")

    case_id: str
    mode: str
    commit_sha: str
    audit_run_id: str
    decision_expected: str
    decision_actual: str
    matched_blockers: list[str] = Field(default_factory=list)
    missed_blockers: list[str] = Field(default_factory=list)
    false_positives: list[str] = Field(default_factory=list)
    evidence_coverage: float = 0.0
    critical_evidence_coverage: float = 0.0
    unsupported_critical: int = 0
    trap_hits: int = 0
    blockers_total: int = 0
    runtime_ms: int = 0
    estimated_cost: float = 0.0
    status: str = "success"

    # Micro-aggregation private attributes (excluded from JSON serialization)
    _held_out: bool = PrivateAttr(default=False)
    _crit_blockers_total: int = PrivateAttr(default=0)
    _crit_blockers_matched: int = PrivateAttr(default=0)
    _high_blockers_total: int = PrivateAttr(default=0)
    _high_blockers_matched: int = PrivateAttr(default=0)
    _total_findings: int = PrivateAttr(default=0)
    _covered_findings: int = PrivateAttr(default=0)
    _crit_high_findings: int = PrivateAttr(default=0)
    _crit_high_covered: int = PrivateAttr(default=0)


def score_case(report: AuditReport | None, gold: dict[str, Any], run_status: str = "completed") -> CaseScore:
    """Score a single case audit report against its gold specification.

    Adheres strictly to ReleaseGuard Evaluation Protocol (eval/EVALUATION_SPEC.md).
    """
    case_id = gold.get("case_id", "unknown_case")
    is_held_out = bool(gold.get("held_out", False))
    decision_expected = gold.get("expected_decision", "")

    gold_blockers = gold.get("blockers", [])
    crit_blockers = [b for b in gold_blockers if b.get("severity") == "critical"]
    high_blockers = [b for b in gold_blockers if b.get("severity") == "high"]
    crit_blockers_total = len(crit_blockers)
    high_blockers_total = len(high_blockers)

    # Failed-run policy (Section 5): a failed run always counts every gold
    # blocker as missed and its decision as incorrect, regardless of what a
    # partial report contains. That policy must not extend to precision,
    # though — if a partial report exists, it can still contain fabricated
    # findings, and those must still count as false positives / trap hits /
    # unsupported-critical, or a system that hallucinates and then crashes
    # would score as if it had done nothing wrong.
    is_failed = run_status == "failed" or report is None

    if report is None:
        score = CaseScore(
            case_id=case_id,
            mode="unknown",
            commit_sha="",
            audit_run_id=f"failed_{case_id}",
            decision_expected=decision_expected,
            decision_actual="FAILED",
            matched_blockers=[],
            missed_blockers=[b["blocker_id"] for b in gold_blockers],
            false_positives=[],
            evidence_coverage=0.0,
            critical_evidence_coverage=0.0,
            unsupported_critical=0,
            trap_hits=0,
            blockers_total=crit_blockers_total,
            runtime_ms=0,
            estimated_cost=0.0,
            status="failed",
        )
        score._held_out = is_held_out
        score._crit_blockers_total = crit_blockers_total
        score._high_blockers_total = high_blockers_total
        return score

    decision_actual = (
        report.decision.value
        if hasattr(report.decision, "value")
        else str(report.decision)
    )

    # 1. Deterministic blocker assignment (Section 2)
    assigned: dict[str, str] = {}  # finding_id -> blocker_id
    for blocker in sorted(gold_blockers, key=lambda b: b["blocker_id"]):
        candidates = []
        for finding in report.findings:
            if finding.id in assigned:
                continue
            f_cat = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
            f_sev = finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity)
            if finding_matches_blocker(
                finding_category=f_cat,
                finding_severity=f_sev,
                finding_title=finding.title,
                finding_claim=finding.claim,
                blocker=blocker,
            ):
                candidates.append(finding)
        if candidates:
            def f_sort_key(f: Finding) -> tuple[float, int]:
                m = re.search(r"\d+", f.id)
                num_id = int(m.group(0)) if m else 0
                return (f.confidence, -num_id)

            best_f = max(candidates, key=f_sort_key)
            assigned[best_f.id] = blocker["blocker_id"]

    matched_blocker_ids = [b["blocker_id"] for b in gold_blockers if b["blocker_id"] in assigned.values()]
    missed_blocker_ids = [b["blocker_id"] for b in gold_blockers if b["blocker_id"] not in assigned.values()]

    # 2. False Positives & Trap Hits (Section 3)
    false_positives: list[str] = []
    trap_hits_count = 0
    crit_high_findings_count = 0

    for finding in report.findings:
        if not _is_crit_or_high(finding.severity):
            # medium, low, info findings excluded from precision entirely
            continue

        crit_high_findings_count += 1
        finding_text = f"{finding.title} {finding.claim}"

        # Trap hit check (Section 3)
        is_trap = any(
            keyword_set_matches(finding_text, words)
            for item in gold.get("forbidden_findings", [])
            for words in item.get("match_any_of", [])
        )
        if is_trap:
            trap_hits_count += 1

        # False positive check:
        if finding.id in assigned:
            # Matched a known blocker -> not a false positive
            continue

        # Check acceptable_extra_findings
        f_cat = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
        is_acceptable = any(
            extra.get("category") == f_cat
            and any(keyword_set_matches(finding_text, words) for words in extra.get("match_any_of", []))
            for extra in gold.get("acceptable_extra_findings", [])
        )
        if not is_acceptable:
            false_positives.append(finding.id)

    # 3. Evidence Coverage (Section 4)
    evidence_by_id = {e.id: e for e in report.evidence}
    covered_findings_count = 0
    crit_high_covered_count = 0
    unsupported_critical_count = 0

    for finding in report.findings:
        is_crit_high = _is_crit_or_high(finding.severity)
        is_covered = False

        if finding.evidence_ids:
            # Every ID in evidence_ids must resolve to an Evidence in report.evidence
            # AND that Evidence must have source_ref == report.commit_sha
            all_resolved = all(
                ev_id in evidence_by_id and evidence_by_id[ev_id].source_ref == report.commit_sha
                for ev_id in finding.evidence_ids
            )
            if all_resolved:
                is_covered = True

        if is_covered:
            covered_findings_count += 1
            if is_crit_high:
                crit_high_covered_count += 1
        else:
            if is_crit_high:
                unsupported_critical_count += 1

    total_findings_count = len(report.findings)
    evidence_cov = (
        covered_findings_count / total_findings_count if total_findings_count > 0 else 0.0
    )
    crit_evidence_cov = (
        crit_high_covered_count / crit_high_findings_count if crit_high_findings_count > 0 else 0.0
    )

    matched_crit_count = sum(1 for b in crit_blockers if b["blocker_id"] in assigned.values())
    matched_high_count = sum(1 for b in high_blockers if b["blocker_id"] in assigned.values())

    if is_failed:
        # Recall side stays failed-by-policy: every gold blocker counts as
        # missed and the run is never eligible for decision_accuracy (status
        # stays "failed"). Precision side (false positives / trap hits /
        # unsupported-critical / evidence coverage) is still scored from
        # whatever the partial report actually claimed.
        score = CaseScore(
            case_id=case_id,
            mode=report.mode,
            commit_sha=report.commit_sha,
            audit_run_id=report.audit_run_id,
            decision_expected=decision_expected,
            decision_actual=decision_actual,
            matched_blockers=[],
            missed_blockers=[b["blocker_id"] for b in gold_blockers],
            false_positives=false_positives,
            evidence_coverage=round(evidence_cov, 4),
            critical_evidence_coverage=round(crit_evidence_cov, 4),
            unsupported_critical=unsupported_critical_count,
            trap_hits=trap_hits_count,
            blockers_total=crit_blockers_total,
            runtime_ms=report.runtime_ms,
            estimated_cost=report.estimated_cost_usd,
            status="failed",
        )
        score._held_out = is_held_out
        score._crit_blockers_total = crit_blockers_total
        score._crit_blockers_matched = 0
        score._high_blockers_total = high_blockers_total
        score._high_blockers_matched = 0
        score._total_findings = total_findings_count
        score._covered_findings = covered_findings_count
        score._crit_high_findings = crit_high_findings_count
        score._crit_high_covered = crit_high_covered_count
        return score

    score = CaseScore(
        case_id=case_id,
        mode=report.mode,
        commit_sha=report.commit_sha,
        audit_run_id=report.audit_run_id,
        decision_expected=decision_expected,
        decision_actual=decision_actual,
        matched_blockers=matched_blocker_ids,
        missed_blockers=missed_blocker_ids,
        false_positives=false_positives,
        evidence_coverage=round(evidence_cov, 4),
        critical_evidence_coverage=round(crit_evidence_cov, 4),
        unsupported_critical=unsupported_critical_count,
        trap_hits=trap_hits_count,
        blockers_total=crit_blockers_total,
        runtime_ms=report.runtime_ms,
        estimated_cost=report.estimated_cost_usd,
        status="success",
    )
    score._held_out = is_held_out
    score._crit_blockers_total = crit_blockers_total
    score._crit_blockers_matched = matched_crit_count
    score._high_blockers_total = high_blockers_total
    score._high_blockers_matched = matched_high_count
    score._total_findings = total_findings_count
    score._covered_findings = covered_findings_count
    score._crit_high_findings = crit_high_findings_count
    score._crit_high_covered = crit_high_covered_count

    return score


def _is_crit_or_high(severity: Severity | str) -> bool:
    val = severity.value if hasattr(severity, "value") else str(severity)
    return val in ("critical", "high")


def _compute_slice_metrics(subset: list[CaseScore]) -> dict[str, Any]:
    n_cases = len(subset)
    if n_cases == 0:
        return {
            "cbr": 0.0,
            "high_blocker_recall": 0.0,
            "precision": 0.0,
            "f1": 0.0,
            "decision_accuracy": 0.0,
            "evidence_coverage": 0.0,
            "critical_evidence_coverage": 0.0,
            "unsupported_critical_total": 0,
            "trap_hits_total": 0,
            "successful_run_rate": 0.0,
            "total_runtime_ms": 0,
            "total_cost": 0.0,
        }

    # Micro Critical Blocker Recall (primary)
    total_crit_blockers = sum(getattr(s, "_crit_blockers_total", s.blockers_total) for s in subset)
    matched_crit_blockers = sum(getattr(s, "_crit_blockers_matched", len(s.matched_blockers)) for s in subset)
    cbr = matched_crit_blockers / total_crit_blockers if total_crit_blockers > 0 else 0.0

    # Micro High Blocker Recall
    total_high_blockers = sum(getattr(s, "_high_blockers_total", 0) for s in subset)
    matched_high_blockers = sum(getattr(s, "_high_blockers_matched", 0) for s in subset)
    high_blocker_recall = matched_high_blockers / total_high_blockers if total_high_blockers > 0 else 0.0

    # Micro Precision: (matched/acceptable crit/high findings) / (total crit/high findings)
    total_crit_high_findings = sum(getattr(s, "_crit_high_findings", 0) for s in subset)
    total_false_positives = sum(len(s.false_positives) for s in subset)
    matched_or_acceptable_crit_high = max(0, total_crit_high_findings - total_false_positives)
    precision = (
        matched_or_acceptable_crit_high / total_crit_high_findings
        if total_crit_high_findings > 0
        else 0.0
    )

    # F1
    if (precision + cbr) > 0:
        f1 = (2 * precision * cbr) / (precision + cbr)
    else:
        f1 = 0.0

    # Decision Accuracy (Macro: scheduled cases with status=success and decision_actual == decision_expected / total cases in slice)
    correct_decisions = sum(
        1 for s in subset
        if s.status == "success" and s.decision_actual == s.decision_expected
    )
    decision_accuracy = correct_decisions / n_cases

    # Evidence Coverage (Micro: covered findings / all findings)
    all_findings_count = sum(getattr(s, "_total_findings", 0) for s in subset)
    all_covered_count = sum(getattr(s, "_covered_findings", 0) for s in subset)
    evidence_coverage = all_covered_count / all_findings_count if all_findings_count > 0 else 0.0

    # Critical Evidence Coverage (Micro: crit/high covered / all crit/high)
    all_crit_high_covered = sum(getattr(s, "_crit_high_covered", 0) for s in subset)
    critical_evidence_coverage = (
        all_crit_high_covered / total_crit_high_findings if total_crit_high_findings > 0 else 0.0
    )

    # Totals
    unsupported_critical_total = sum(s.unsupported_critical for s in subset)
    trap_hits_total = sum(s.trap_hits for s in subset)
    successful_runs = sum(1 for s in subset if s.status == "success")
    successful_run_rate = successful_runs / n_cases
    total_runtime_ms = sum(s.runtime_ms for s in subset)
    total_cost = sum(s.estimated_cost for s in subset)

    return {
        "cbr": round(cbr, 4),
        "high_blocker_recall": round(high_blocker_recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "decision_accuracy": round(decision_accuracy, 4),
        "evidence_coverage": round(evidence_coverage, 4),
        "critical_evidence_coverage": round(critical_evidence_coverage, 4),
        "unsupported_critical_total": unsupported_critical_total,
        "trap_hits_total": trap_hits_total,
        "successful_run_rate": round(successful_run_rate, 4),
        "total_runtime_ms": total_runtime_ms,
        "total_cost": round(total_cost, 4),
    }


def aggregate(scores: list[CaseScore]) -> dict[str, dict[str, Any]]:
    """Aggregate per-case scores into three slices: development, held_out, all."""
    dev_cases: list[CaseScore] = []
    held_out_cases: list[CaseScore] = []

    for s in scores:
        is_held_out = getattr(s, "_held_out", s.case_id in {"case_09", "case_10", "case_11", "case_12"})
        if is_held_out:
            held_out_cases.append(s)
        else:
            dev_cases.append(s)

    return {
        "development": _compute_slice_metrics(dev_cases),
        "held_out": _compute_slice_metrics(held_out_cases),
        "all": _compute_slice_metrics(scores),
    }
