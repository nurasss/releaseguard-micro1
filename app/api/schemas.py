# path: app/api/schemas.py
"""Pydantic request/response models for the ReleaseGuard HTTP API (TZ Section 31)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_url: str
    ref: str = "main"
    # Profile selection is reserved for a future policy registry; this request
    # field is accepted for compatibility and currently uses default behavior.
    profile: str = "default-release"
    # The product is the final Analyzer -> Verifier pipeline. B1 is the
    # deliberately weakened control kept for evaluation, so a caller that omits
    # the field must not silently receive it.
    mode: Literal["baseline", "final"] = "final"


class CreateAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    # MVP simplification: since /api/v1/audits runs the audit synchronously
    # in-process (no queue/background worker; true async queuing is out of
    # scope per TZ Section 38 priority cuts), this reflects the *actual*
    # AuditRun.status once the run has already completed, not a literal
    # "queued" placeholder.
    status: str


class AuditDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    run: dict[str, Any]
    report: dict[str, Any] | None = None


class FindingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    findings: list[dict[str, Any]] = Field(default_factory=list)


class CreateEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["baseline", "final"]
    cases: list[str] | None = None


class CreateEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    status: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
