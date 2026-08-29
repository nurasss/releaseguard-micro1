# path: tests/test_evidence_store.py
import re
from pathlib import Path

import pytest

from app.evidence.store import EvidenceStore
from app.schemas.enums import Decision, FindingCategory, Severity, SourceType, VerificationStatus
from app.schemas.findings import Finding
from app.schemas.integrity import validate_report_integrity
from app.schemas.report import AuditReport
from app.schemas.verification import VerificationResult


def test_evidence_store_sequential_ids_and_regex() -> None:
    store = EvidenceStore(audit_run_id="run-001", commit_sha="a" * 40)
    pattern = re.compile(r"^E-\d{3,}$")

    for i in range(1, 251):
        ev = store.add(
            source_type=SourceType.github_file,
            source_path=f"src/file_{i}.py",
            summary=f"Evidence item {i}",
            payload={"index": i},
        )
        assert pattern.match(ev.id), f"ID {ev.id} does not match pattern"
        assert ev.id == f"E-{i:03d}"
        assert ev.audit_run_id == "run-001"
        assert ev.source_ref == "a" * 40

    assert len(store.all()) == 250
    assert store.get("E-001") is not None
    assert store.get("E-250") is not None
    assert store.get("E-251") is None


def test_evidence_content_hash_resolution() -> None:
    store = EvidenceStore(audit_run_id="run-001", commit_sha="b" * 40)

    # 1. With explicit text content
    ev1 = store.add(
        source_type=SourceType.github_file,
        source_path="src/main.py",
        summary="Read main.py",
        payload={"dummy": 1},
        content="print('hello')",
    )
    assert len(ev1.content_hash) == 71  # "sha256:" + 64 hex chars = 71
    assert ev1.content_hash.startswith("sha256:")

    # 2. Fallback to payload serialization
    ev2 = store.add(
        source_type=SourceType.repository_metadata,
        source_path="repository_metadata.json",
        summary="Metadata",
        payload={"default_branch": "main"},
    )
    assert len(ev2.content_hash) == 71
    assert ev2.content_hash.startswith("sha256:")
    assert ev1.content_hash != ev2.content_hash


def test_evidence_store_passes_integrity_validation() -> None:
    run_id = "run-test-integrity"
    commit_sha = "c" * 40
    store = EvidenceStore(audit_run_id=run_id, commit_sha=commit_sha)

    ev = store.add(
        source_type=SourceType.github_file,
        source_path="pyproject.toml",
        summary="Read manifest",
        payload={"version": "1.0.0"},
        content="[project]\nversion = '1.0.0'",
    )

    finding = Finding(
        id="F-001",
        audit_run_id=run_id,
        category=FindingCategory.release_metadata,
        severity=Severity.low,
        confidence=0.9,
        title="Valid metadata",
        claim="Metadata looks consistent.",
        recommended_action="Proceed with normal release pipeline.",
        evidence_ids=[ev.id],
    )

    report = AuditReport(
        audit_run_id=run_id,
        repository_url="https://github.com/example/repo",
        requested_ref="main",
        commit_sha=commit_sha,
        mode="test",
        decision=Decision.GO,
        executive_summary="Clean release",
        findings=[finding],
        verifications=[],
        evidence=store.all(),
        deterministic_checks=[],
        limitations=[],
        runtime_ms=500,
        model_id="gemini-2.5-flash",
        prompt_version="p1",
        estimated_cost_usd=0.0,
    )

    violations = validate_report_integrity(report)
    assert not violations, f"Unexpected integrity violations: {violations}"
