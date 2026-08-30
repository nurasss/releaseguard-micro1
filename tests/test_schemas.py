from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas.audit import AgentStep, AuditRun, DeterministicCheckResult
from app.schemas.enums import (
    CheckStatus,
    Decision,
    FindingCategory,
    RunStatus,
    Severity,
    SourceType,
    VerifierStatus,
)
from app.schemas.evidence import Evidence, content_hash_of
from app.schemas.findings import Finding
from app.schemas.plan import AuditPlan
from app.schemas.verification import VerificationResult


def test_valid_evidence_creation() -> None:
    data = "print('hello world')"
    chash = content_hash_of(data)
    assert chash.startswith("sha256:")
    assert len(chash) == 7 + 64

    ev = Evidence(
        id="E-001",
        audit_run_id="run-123",
        source_type=SourceType.github_file,
        source_path="src/main.py",
        source_ref="0123456789abcdef0123456789abcdef01234567",
        line_start=10,
        line_end=20,
        content_hash=chash,
        summary="A simple test evidence summary.",
        payload={"raw": "content"},
    )
    assert ev.id == "E-001"
    assert ev.line_start == 10
    assert ev.line_end == 20
    assert ev.source_type == SourceType.github_file


def test_content_hash_of_bytes_and_str() -> None:
    hash_str = content_hash_of("sample text")
    hash_bytes = content_hash_of(b"sample text")
    assert hash_str == hash_bytes
    assert hash_str.startswith("sha256:")


def test_invalid_evidence_id() -> None:
    valid_sha = "0123456789abcdef0123456789abcdef01234567"
    valid_hash = "sha256:" + "a" * 64

    with pytest.raises(ValidationError):
        Evidence(
            id="E-12",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            content_hash=valid_hash,
            summary="summary",
        )

    with pytest.raises(ValidationError):
        Evidence(
            id="EV-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            content_hash=valid_hash,
            summary="summary",
        )


def test_invalid_evidence_source_ref() -> None:
    valid_hash = "sha256:" + "a" * 64

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref="0123456789ABCDEF0123456789ABCDEF01234567",
            content_hash=valid_hash,
            summary="summary",
        )

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref="0123456",
            content_hash=valid_hash,
            summary="summary",
        )


def test_invalid_evidence_content_hash() -> None:
    valid_sha = "0123456789abcdef0123456789abcdef01234567"

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            content_hash="a" * 64,
            summary="summary",
        )

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            content_hash="sha256:" + "z" * 64,
            summary="summary",
        )


def test_evidence_line_range_validation() -> None:
    valid_sha = "0123456789abcdef0123456789abcdef01234567"
    valid_hash = "sha256:" + "a" * 64

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            line_start=20,
            line_end=10,
            content_hash=valid_hash,
            summary="summary",
        )

    with pytest.raises(ValidationError):
        Evidence(
            id="E-100",
            audit_run_id="run-1",
            source_type=SourceType.github_file,
            source_path="foo.py",
            source_ref=valid_sha,
            line_start=None,
            line_end=10,
            content_hash=valid_hash,
            summary="summary",
        )


def test_critical_finding_with_empty_evidence_ids_succeeds() -> None:
    # Model MUST NOT fail when severity=critical and evidence_ids is empty.
    # It must be accepted during parsing and caught later by integrity check.
    finding = Finding(
        id="F-001",
        audit_run_id="run-001",
        category=FindingCategory.security,
        title="Unverified security issue",
        severity=Severity.critical,
        claim="Hardcoded secret detected",
        confidence=0.95,
        evidence_ids=[],
        recommended_action="Rotate credentials immediately",
    )
    assert finding.id == "F-001"
    assert finding.severity == Severity.critical
    assert finding.evidence_ids == []
    assert finding.requires_verification is True


def test_finding_requires_verification() -> None:
    f_crit = Finding(
        id="F-101",
        audit_run_id="run-1",
        category=FindingCategory.ci,
        title="Critical CI failure",
        severity=Severity.critical,
        claim="Main branch build broken",
        confidence=0.9,
        recommended_action="Fix build",
    )
    assert f_crit.requires_verification is True

    f_high = Finding(
        id="F-102",
        audit_run_id="run-1",
        category=FindingCategory.tests,
        title="High severity test flake",
        severity=Severity.high,
        claim="Integration test flaky",
        confidence=0.8,
        recommended_action="Investigate flakiness",
    )
    assert f_high.requires_verification is True

    f_med = Finding(
        id="F-103",
        audit_run_id="run-1",
        category=FindingCategory.docs,
        title="Outdated readme",
        severity=Severity.medium,
        claim="Docs missing setup steps",
        confidence=0.7,
        recommended_action="Update readme",
    )
    assert f_med.requires_verification is False


def test_finding_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="F-001",
            audit_run_id="run-001",
            category=FindingCategory.ci,
            title="CI issue",
            severity=Severity.low,
            claim="Claim text",
            confidence=1.5,
            recommended_action="Action",
        )

    with pytest.raises(ValidationError):
        Finding(
            id="F-001",
            audit_run_id="run-001",
            category=FindingCategory.ci,
            title="CI issue",
            severity=Severity.low,
            claim="Claim text",
            confidence=-0.1,
            recommended_action="Action",
        )


def test_finding_extra_fields_ignored() -> None:
    data = {
        "id": "F-001",
        "audit_run_id": "run-001",
        "category": "security",
        "title": "Extra field finding",
        "severity": "critical",
        "claim": "Claim with extra field",
        "confidence": 0.9,
        "evidence_ids": ["E-001"],
        "recommended_action": "Fix it",
        "rationale": "LLM added extra explanation field",
        "notes": "Another hallucinated key",
    }
    finding = Finding.model_validate(data)
    assert finding.id == "F-001"
    assert not hasattr(finding, "rationale")
    assert not hasattr(finding, "notes")
    assert "rationale" not in finding.model_dump()


def test_verification_result_validator() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            finding_id="F-001",
            status=VerifierStatus.confirmed,
            confidence=0.5,
            reason_summary="Error occurred",
            verifier_error="LLM JSON syntax error",
        )

    res = VerificationResult(
        finding_id="F-001",
        status=VerifierStatus.uncertain,
        confidence=0.0,
        reason_summary="Verifier could not parse model response",
        verifier_error="LLM JSON syntax error",
    )
    assert res.status == VerifierStatus.uncertain
    assert res.verifier_error == "LLM JSON syntax error"


def test_verification_result_extra_fields_ignored() -> None:
    data = {
        "finding_id": "F-001",
        "status": "uncertain",
        "confidence": 0.5,
        "reason_summary": "Uncertain verdict",
        "llm_chain_of_thought": "I am thinking step by step...",
    }
    res = VerificationResult.model_validate(data)
    assert res.finding_id == "F-001"
    assert not hasattr(res, "llm_chain_of_thought")


def test_audit_plan_from_agent_payload() -> None:
    wrapped_payload = {
        "audit_plan": {
            "areas": ["ci", "dependencies", "security"],
            "questions": ["Are all tests passing?"],
            "required_tools": ["git_log", "read_file"],
            "extra_field": "some LLM metadata",
        }
    }
    plan1 = AuditPlan.from_agent_payload(wrapped_payload)
    assert plan1.areas == ["ci", "dependencies", "security"]
    assert plan1.questions == ["Are all tests passing?"]
    assert len(plan1.required_tools) == 2
    assert not hasattr(plan1, "extra_field")

    flat_payload = {
        "areas": ["build", "tests"],
        "questions": [],
        "required_tools": [],
    }
    plan2 = AuditPlan.from_agent_payload(flat_payload)
    assert plan2.areas == ["build", "tests"]

    with pytest.raises(ValidationError):
        AuditPlan.from_agent_payload({"areas": []})


def test_audit_plan_extra_fields_ignored() -> None:
    data = {
        "areas": ["ci"],
        "questions": ["Is CI configured?"],
        "hallucinated_property": "should be ignored",
    }
    plan = AuditPlan.model_validate(data)
    assert plan.areas == ["ci"]
    assert not hasattr(plan, "hallucinated_property")
    assert "hallucinated_property" not in plan.model_dump()


def test_deterministic_check_result_schema() -> None:
    dc = DeterministicCheckResult(
        check_id="DC-01",
        name="Branch Protection Check",
        status=CheckStatus.pass_,
        details="Main branch requires 1 approval",
        evidence_ids=["E-001"],
    )
    assert dc.check_id == "DC-01"
    assert dc.status == CheckStatus.pass_

    with pytest.raises(ValidationError):
        DeterministicCheckResult(
            check_id="DC-1",
            name="Check",
            status=CheckStatus.fail,
            details="Failed",
        )


def test_agent_step_and_audit_run_schemas() -> None:
    step = AgentStep(
        audit_run_id="run-1",
        sequence=1,
        component="orchestrator",
        state="planning",
        tool="list_files",
        input_redacted={"path": "."},
        output_summary="Found 10 files",
        evidence_created=["E-001"],
        duration_ms=150,
        status="success",
        retry=0,
        timestamp="2026-08-29T00:00:00Z",
    )
    assert step.sequence == 1
    assert step.component == "orchestrator"

    run = AuditRun(
        id="run-1",
        repository_url="https://github.com/example/repo",
        requested_ref="main",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        status=RunStatus.completed,
        final_decision=Decision.GO,
        started_at="2026-08-29T00:00:00Z",
        finished_at="2026-08-29T00:05:00Z",
        runtime_ms=300000,
        estimated_cost_usd=0.05,
        model_id="claude-sonnet-5",
        prompt_version="p1",
        system_version="0.1.0",
        mode="final",
    )
    assert run.id == "run-1"
    assert run.final_decision == Decision.GO


def test_settings_masks_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_API_KEY", "super-secret-token-12345")
    monkeypatch.setenv("RG_GITHUB_TOKEN", "super-secret-gh-token-67890")
    monkeypatch.setenv("RG_MODEL_ID", "custom-model")

    settings = Settings()
    assert settings.api_key == "super-secret-token-12345"
    assert settings.github_token == "super-secret-gh-token-67890"
    assert settings.model_id == "custom-model"

    repr_str = repr(settings)
    str_val = str(settings)

    # API key and GitHub token must NEVER be revealed in repr or str
    assert "super-secret-token-12345" not in repr_str
    assert "super-secret-token-12345" not in str_val
    assert "super-secret-gh-token-67890" not in repr_str
    assert "super-secret-gh-token-67890" not in str_val
    assert "***" in repr_str
    assert "***" in str_val


def test_settings_accepts_and_masks_xai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_LLM_PROVIDER", "xai")
    monkeypatch.setenv("RG_MODEL_ID", "grok-4.6")
    monkeypatch.setenv("XAI_API_KEY", "xai-super-secret-token")

    settings = Settings()
    assert settings.llm_provider == "xai"
    assert settings.model_id == "grok-4.6"
    assert settings.xai_api_key == "xai-super-secret-token"
    assert "xai-super-secret-token" not in repr(settings)
    assert "xai_super_secret_token" not in str(settings)
