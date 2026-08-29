from __future__ import annotations

from pathlib import Path

from app.schemas.audit import AgentStep, AuditRun
from app.schemas.enums import (
    Decision,
    FindingCategory,
    RunStatus,
    Severity,
    SourceType,
    VerificationStatus,
    VerifierStatus,
)
from app.schemas.evidence import Evidence, content_hash_of
from app.schemas.findings import Finding
from app.schemas.verification import VerificationResult
from app.storage.db import connect, init_db
from app.storage.repository import AuditRepository


def test_init_db_idempotency_and_migrations(tmp_path: Path) -> None:
    db_file = tmp_path / "idempotent.sqlite3"
    conn = connect(db_file)

    init_db(conn)

    cursor = conn.execute("SELECT version, applied_at FROM schema_migrations;")
    migrations = cursor.fetchall()
    assert len(migrations) == 1
    assert migrations[0]["version"] == "1"
    assert migrations[0]["applied_at"].endswith("Z")

    init_db(conn)

    cursor = conn.execute("SELECT version, applied_at FROM schema_migrations;")
    migrations_after = cursor.fetchall()
    assert len(migrations_after) == 1

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}
    assert "audit_runs" in tables
    assert "evidence" in tables
    assert "findings" in tables
    assert "finding_evidence" in tables
    assert "verification_results" in tables
    assert "agent_steps" in tables
    assert "evaluation_cases" in tables
    assert "evaluation_results" in tables
    assert "schema_migrations" in tables
    conn.close()


def test_full_roundtrip_storage(tmp_path: Path) -> None:
    db_file = tmp_path / "roundtrip.sqlite3"
    conn = connect(db_file)
    init_db(conn)
    repo = AuditRepository(conn)

    run_id = "run-test-001"
    sha = "0123456789abcdef0123456789abcdef01234567"

    run = AuditRun(
        id=run_id,
        repository_url="https://github.com/example/repo",
        requested_ref="release-1.0",
        commit_sha=sha,
        status=RunStatus.completed,
        final_decision=Decision.GO,
        started_at="2026-08-29T01:00:00Z",
        finished_at="2026-08-29T01:05:00Z",
        runtime_ms=300000,
        estimated_cost_usd=0.045,
        model_id="claude-sonnet-5",
        prompt_version="p1",
        system_version="0.1.0",
        mode="final",
    )
    repo.save_run(run)
    saved_run = repo.get_run(run_id)
    assert saved_run is not None
    assert saved_run == run

    assert repo.get_run("nonexistent-run") is None

    ev1 = Evidence(
        id="E-001",
        audit_run_id=run_id,
        source_type=SourceType.manifest,
        source_path="pyproject.toml",
        source_ref=sha,
        line_start=1,
        line_end=15,
        content_hash=content_hash_of("content1"),
        summary="Pyproject manifest",
        payload={"pkg_count": 5},
    )
    ev2 = Evidence(
        id="E-002",
        audit_run_id=run_id,
        source_type=SourceType.github_actions,
        source_path=".github/workflows/ci.yml",
        source_ref=sha,
        line_start=10,
        line_end=50,
        content_hash=content_hash_of("content2"),
        summary="CI workflow configuration",
        payload={"jobs": ["test", "build"]},
    )
    ev1000 = Evidence(
        id="E-1000",
        audit_run_id=run_id,
        source_type=SourceType.github_file,
        source_path="large_file.py",
        source_ref=sha,
        line_start=1,
        line_end=10,
        content_hash=content_hash_of("content1000"),
        summary="High index evidence",
        payload={},
    )
    ev999 = Evidence(
        id="E-999",
        audit_run_id=run_id,
        source_type=SourceType.github_file,
        source_path="mid_file.py",
        source_ref=sha,
        line_start=1,
        line_end=10,
        content_hash=content_hash_of("content999"),
        summary="Mid index evidence",
        payload={},
    )
    repo.save_evidence([ev1000, ev1, ev999, ev2])
    saved_evs = repo.get_evidence(run_id)
    assert len(saved_evs) == 4
    assert saved_evs[0] == ev1
    assert saved_evs[1] == ev2
    assert saved_evs[2] == ev999
    assert saved_evs[3] == ev1000

    f1 = Finding(
        id="F-001",
        audit_run_id=run_id,
        category=FindingCategory.ci,
        title="CI job failure",
        severity=Severity.critical,
        claim="CI job failed on main",
        confidence=0.98,
        evidence_ids=["E-001", "E-002"],
        recommended_action="Investigate CI failures",
        verification_status=VerificationStatus.confirmed,
        origin="analyzer",
    )
    f2 = Finding(
        id="F-002",
        audit_run_id=run_id,
        category=FindingCategory.security,
        title="Dependency vulnerability",
        severity=Severity.medium,
        claim="CVE in old library",
        confidence=0.85,
        evidence_ids=["E-001"],
        recommended_action="Upgrade dependency",
        verification_status=VerificationStatus.pending,
        origin="deterministic",
    )
    f1000 = Finding(
        id="F-1000",
        audit_run_id=run_id,
        category=FindingCategory.other,
        title="High index finding",
        severity=Severity.low,
        claim="Minor finding",
        confidence=0.5,
        evidence_ids=["E-1000"],
        recommended_action="Review",
        verification_status=VerificationStatus.needs_human_review,
        origin="baseline",
    )
    f999 = Finding(
        id="F-999",
        audit_run_id=run_id,
        category=FindingCategory.docs,
        title="Mid index finding",
        severity=Severity.info,
        claim="Docs comment",
        confidence=0.6,
        evidence_ids=["E-999"],
        recommended_action="Update",
        verification_status=VerificationStatus.rejected,
        origin="analyzer",
    )
    repo.save_findings([f1000, f1, f999, f2])
    saved_findings = repo.get_findings(run_id)
    assert len(saved_findings) == 4
    assert saved_findings[0] == f1
    assert saved_findings[1] == f2
    assert saved_findings[2] == f999
    assert saved_findings[3] == f1000

    v1 = VerificationResult(
        finding_id="F-001",
        status=VerifierStatus.confirmed,
        confidence=0.95,
        supporting_evidence=["E-001"],
        contradicting_evidence=[],
        reason_summary="Logs confirmed CI failure on commit",
        verifier_error=None,
    )
    v2 = VerificationResult(
        finding_id="F-002",
        status=VerifierStatus.uncertain,
        confidence=0.0,
        supporting_evidence=["E-001"],
        contradicting_evidence=["E-002"],
        reason_summary="Verifier could not parse provider output",
        verifier_error="invalid JSON from provider",
    )
    repo.save_verification(v1, run_id)
    repo.save_verification(v2, run_id)
    saved_verifications = repo.get_verifications(run_id)
    assert len(saved_verifications) == 2
    assert saved_verifications[0] == v1
    assert saved_verifications[1] == v2

    step3 = AgentStep(
        audit_run_id=run_id,
        sequence=3,
        component="verifier",
        state="verifying",
        tool="grep",
        input_redacted={"query": "error"},
        output_summary="Found 1 match",
        evidence_created=["E-002"],
        duration_ms=200,
        status="success",
        retry=0,
        timestamp="2026-08-29T01:02:00Z",
    )
    step1 = AgentStep(
        audit_run_id=run_id,
        sequence=1,
        component="orchestrator",
        state="planning",
        tool=None,
        input_redacted={},
        output_summary="Created plan",
        evidence_created=[],
        duration_ms=100,
        status="success",
        retry=0,
        timestamp="2026-08-29T01:00:10Z",
    )
    step2 = AgentStep(
        audit_run_id=run_id,
        sequence=2,
        component="analyzer",
        state="analyzing",
        tool="read_file",
        input_redacted={"file": "pyproject.toml"},
        output_summary="Read pyproject",
        evidence_created=["E-001"],
        duration_ms=150,
        status="success",
        retry=0,
        timestamp="2026-08-29T01:01:00Z",
    )

    repo.save_agent_step(step3)
    repo.save_agent_step(step1)
    repo.save_agent_step(step2)

    saved_steps = repo.get_agent_steps(run_id)
    assert len(saved_steps) == 3
    assert [s.sequence for s in saved_steps] == [1, 2, 3]
    assert saved_steps[0] == step1
    assert saved_steps[1] == step2
    assert saved_steps[2] == step3

    repo.save_evaluation_result(
        case_id="case-001",
        run_id=run_id,
        mode="final",
        recall=1.0,
        precision=0.9,
        f1=0.947,
        evidence_coverage=1.0,
        decision_correct=True,
        runtime_ms=300000,
        estimated_cost=0.045,
    )
    cursor = conn.execute("SELECT * FROM evaluation_results WHERE case_id = ?;", ("case-001",))
    eval_row = cursor.fetchone()
    assert eval_row is not None
    assert eval_row["case_id"] == "case-001"
    assert eval_row["decision_correct"] == 1
    assert eval_row["f1"] == 0.947

    updated_run = run.model_copy(update={"status": RunStatus.failed, "runtime_ms": 400000})
    repo.update_run(updated_run)
    reloaded_run = repo.get_run(run_id)
    assert reloaded_run is not None
    assert reloaded_run.status == RunStatus.failed
    assert reloaded_run.runtime_ms == 400000

    conn.close()


def test_idempotent_writes(tmp_path: Path) -> None:
    db_file = tmp_path / "idempotent_writes.sqlite3"
    conn = connect(db_file)
    init_db(conn)
    repo = AuditRepository(conn)

    run_id = "run-idem-001"
    sha = "0123456789abcdef0123456789abcdef01234567"

    run = AuditRun(
        id=run_id,
        repository_url="https://github.com/example/repo",
        requested_ref="main",
        commit_sha=sha,
        status=RunStatus.running,
        started_at="2026-08-29T01:00:00Z",
        model_id="claude-sonnet-5",
        prompt_version="p1",
        system_version="0.1.0",
    )
    repo.save_run(run)

    step = AgentStep(
        audit_run_id=run_id,
        sequence=1,
        component="orchestrator",
        state="executing",
        tool="git_status",
        input_redacted={"arg": "value"},
        output_summary="Done",
        evidence_created=["E-001"],
        duration_ms=50,
        status="success",
        retry=0,
        timestamp="2026-08-29T01:00:05Z",
    )
    repo.save_agent_step(step)
    repo.save_agent_step(step)

    steps = repo.get_agent_steps(run_id)
    assert len(steps) == 1
    assert steps[0] == step

    ver = VerificationResult(
        finding_id="F-001",
        status=VerifierStatus.uncertain,
        confidence=0.2,
        supporting_evidence=["E-001"],
        contradicting_evidence=["E-002"],
        reason_summary="Ambiguous evidence",
        verifier_error="invalid JSON from provider",
    )
    repo.save_verification(ver, run_id)
    repo.save_verification(ver, run_id)

    verifications = repo.get_verifications(run_id)
    assert len(verifications) == 1
    assert verifications[0] == ver

    conn.close()


def test_numeric_sorting_evidence_and_findings(tmp_path: Path) -> None:
    db_file = tmp_path / "sorting.sqlite3"
    conn = connect(db_file)
    init_db(conn)
    repo = AuditRepository(conn)

    run_id = "run-sort"
    sha = "0123456789abcdef0123456789abcdef01234567"
    run = AuditRun(
        id=run_id,
        repository_url="https://github.com/example/repo",
        requested_ref="main",
        commit_sha=sha,
        status=RunStatus.completed,
        started_at="2026-08-29T01:00:00Z",
        model_id="claude-sonnet-5",
        prompt_version="p1",
        system_version="0.1.0",
    )
    repo.save_run(run)

    ids = ["E-1000", "E-010", "E-002", "E-100", "E-001", "E-999"]
    ev_list = [
        Evidence(
            id=eid,
            audit_run_id=run_id,
            source_type=SourceType.github_file,
            source_path="file.py",
            source_ref=sha,
            content_hash=content_hash_of(eid),
            summary=f"Summary for {eid}",
        )
        for eid in ids
    ]
    repo.save_evidence(ev_list)

    sorted_evs = repo.get_evidence(run_id)
    expected_order = ["E-001", "E-002", "E-010", "E-100", "E-999", "E-1000"]
    assert [e.id for e in sorted_evs] == expected_order

    f_ids = ["F-1000", "F-010", "F-002", "F-100", "F-001", "F-999"]
    f_list = [
        Finding(
            id=fid,
            audit_run_id=run_id,
            category=FindingCategory.ci,
            title=f"Finding {fid}",
            severity=Severity.low,
            claim="Claim",
            confidence=0.5,
            recommended_action="Action",
        )
        for fid in f_ids
    ]
    repo.save_findings(f_list)

    sorted_findings = repo.get_findings(run_id)
    expected_f_order = ["F-001", "F-002", "F-010", "F-100", "F-999", "F-1000"]
    assert [f.id for f in sorted_findings] == expected_f_order

    conn.close()
