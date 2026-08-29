from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import Decision, Severity, VerificationStatus
from app.schemas.evidence import Evidence
from app.schemas.findings import Finding
from app.schemas.verification import VerificationResult


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema_version: Literal["1.0"] = "1.0"
    audit_run_id: str
    repository_url: str
    requested_ref: str
    commit_sha: str
    mode: str
    decision: Decision
    executive_summary: str
    findings: list[Finding] = Field(default_factory=list)
    rejected_findings: list[Finding] = Field(default_factory=list)
    verifications: list[VerificationResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    deterministic_checks: list[DeterministicCheckResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    runtime_ms: int
    model_id: str
    prompt_version: str
    estimated_cost_usd: float = 0.0

    def confirmed_blockers(self) -> list[Finding]:
        """Return findings where severity == critical and verification_status == confirmed."""
        return [
            f
            for f in self.findings
            if f.severity == Severity.critical
            and f.verification_status == VerificationStatus.confirmed
        ]

    def evidence_by_id(self) -> dict[str, Evidence]:
        """Return a mapping of evidence_id to Evidence object."""
        return {e.id: e for e in self.evidence}
