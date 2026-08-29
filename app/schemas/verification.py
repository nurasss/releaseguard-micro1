from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import VerifierStatus


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    finding_id: str
    status: VerifierStatus
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    reason_summary: str
    verifier_error: str | None = None

    @model_validator(mode="after")
    def validate_error_status(self) -> VerificationResult:
        if self.verifier_error is not None and self.status != VerifierStatus.uncertain:
            raise ValueError(
                f"status must be uncertain when verifier_error is present, got {self.status}"
            )
        return self
