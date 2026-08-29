from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import FindingCategory, Severity, VerificationStatus


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^F-\d{3,}$")
    audit_run_id: str
    category: FindingCategory
    title: str = Field(min_length=1, max_length=200)
    severity: Severity
    claim: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    # ВАЖНО: модель НЕ должна падать, если severity=critical и evidence_ids пустой.
    # Такой finding обязан быть принят при парсинге и пойман позже интегрити-чеком —
    # иначе мы не сможем посчитать метрику unsupported_critical_findings.
    evidence_ids: list[str] = Field(default_factory=list)
    recommended_action: str
    verification_status: VerificationStatus = VerificationStatus.pending
    origin: Literal["analyzer", "baseline", "deterministic"] = "analyzer"

    @property
    def requires_verification(self) -> bool:
        """True for severity critical or high."""
        return self.severity in (Severity.critical, Severity.high)
