from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class AuditPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    areas: list[str] = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)

    @classmethod
    def from_agent_payload(cls, payload: dict[str, Any]) -> AuditPlan:
        """Parse AuditPlan from payload accepting either {'audit_plan': {...}} or flat dict."""
        if "audit_plan" in payload and isinstance(payload["audit_plan"], dict):
            return cls.model_validate(payload["audit_plan"])
        return cls.model_validate(payload)
