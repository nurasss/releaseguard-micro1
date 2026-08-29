from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import CheckStatus, Decision, RunStatus


class DeterministicCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(pattern=r"^DC-\d{2}$")
    name: str
    status: CheckStatus
    details: str
    evidence_ids: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_run_id: str
    sequence: int
    component: str  # orchestrator|analyzer|verifier|baseline|tools
    state: str
    tool: str | None = None
    input_redacted: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    evidence_created: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    status: str = "success"
    retry: int = 0
    timestamp: str  # UTC ISO Z


class AuditRun(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    id: str
    repository_url: str
    requested_ref: str
    commit_sha: str
    status: RunStatus
    final_decision: Decision | None = None
    started_at: str
    finished_at: str | None = None
    runtime_ms: int | None = None
    estimated_cost_usd: float = 0.0
    model_id: str
    prompt_version: str
    system_version: str
    mode: Literal["baseline", "final", "ablation"] = "final"
