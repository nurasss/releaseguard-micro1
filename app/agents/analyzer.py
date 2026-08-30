# path: app/agents/analyzer.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.store import EvidenceStore
from app.llm.types import LLMClient, Message, ToolCall
from app.security.redaction import redact_obj
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import Severity, VerificationStatus
from app.schemas.findings import Finding
from app.schemas.plan import AuditPlan
from app.sources.base import RepositorySource, ResolvedRef
from app.tools.dispatch import ToolDispatcher
from app.tools.registry import build_tool_specs
from app.trajectory.logger import TrajectoryLogger


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "audit_plan": {
            "type": "object",
            "properties": {
                "areas": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "required_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["areas", "questions", "required_tools"],
        },
    },
    "required": ["audit_plan"],
}

FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "ci",
                            "tests",
                            "build",
                            "release_metadata",
                            "dependencies",
                            "config",
                            "migrations",
                            "security",
                            "docs",
                            "other",
                        ],
                    },
                    "title": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low", "info"],
                    },
                    "claim": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "recommended_action": {"type": "string"},
                },
                "required": [
                    "category",
                    "title",
                    "severity",
                    "claim",
                    "confidence",
                    "evidence_ids",
                    "recommended_action",
                ],
            },
        },
    },
    "required": ["findings"],
}


class AnalyzerOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "failed"]
    failure_reason: str | None = None
    usage_prompt_tokens: int = 0
    usage_output_tokens: int = 0
    usage_total_tokens: int = 0
    turns: int = 0
    audit_plan: AuditPlan | None = None
    findings: list[Finding] = Field(default_factory=list)
    rejected_findings: list[dict] = Field(default_factory=list)


class AnalyzerAgent:
    """Analyzer agent: forced plan, tool-calling exploration, schema-constrained findings."""

    def __init__(
        self,
        llm: LLMClient,
        source: RepositorySource,
        dispatcher: ToolDispatcher,
        evidence_store: EvidenceStore,
        logger: TrajectoryLogger,
        deterministic_checks: list[DeterministicCheckResult] | None = None,
        max_turns: int = 10,
        deadline_s: int = 300,
        prompt_path: Path | None = None,
    ) -> None:
        self.llm = llm
        self.source = source
        self.dispatcher = dispatcher
        self.evidence_store = evidence_store
        self.logger = logger
        self.deterministic_checks = deterministic_checks or []
        self.max_turns = max_turns
        self.deadline_s = deadline_s
        self.prompt_path = prompt_path or (PROMPTS_DIR / "analyzer.md")

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return (
            "Assess whether this repository is ready for release. Build a plan, gather "
            "evidence via read-only tools, and report findings."
        )

    def _format_deterministic_checks(self) -> str:
        if not self.deterministic_checks:
            return "No deterministic check results are available for this run."

        lines = ["Deterministic check results (treat as trustworthy evidence):"]
        for check in self.deterministic_checks:
            lines.append(
                f"- {check.check_id} ({check.name}): status={check.status.value}; "
                f"details={check.details}; evidence_ids={check.evidence_ids}"
            )
        return "\n".join(lines)

    def run(
        self,
        repository_url: str,
        resolved_ref: ResolvedRef,
        audit_run_id: str,
    ) -> AnalyzerOutcome:
        start_time = time.time()
        system_prompt = self._load_prompt()
        prompt_tokens = 0
        output_tokens = 0
        total_tokens = 0
        turns_count = 0

        # ==========================================
        # PHASE 1: Forced schema-constrained plan
        # ==========================================
        plan_prompt_msg = (
            f"Build an audit plan for repository {repository_url} "
            f"at ref {resolved_ref.requested_ref} (commit {resolved_ref.commit_sha}). "
            "Do not call any tools yet. Return only the audit plan JSON."
        )
        plan_messages: list[Message] = [Message(role="user", content=plan_prompt_msg)]

        turns_count += 1
        try:
            plan_res = self.llm.generate(
                system=system_prompt,
                messages=plan_messages,
                tools=None,
                response_schema=PLAN_SCHEMA,
            )
        except Exception as exc:
            return AnalyzerOutcome(
                status="failed",
                failure_reason=f"LLM plan generation failed: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        prompt_tokens += plan_res.usage.prompt_tokens
        output_tokens += plan_res.usage.output_tokens
        total_tokens += plan_res.usage.total_tokens

        self.logger.log(
            component="analyzer",
            state="plan_generate",
            output_summary=plan_res.text[:200] if plan_res.text else "Empty response",
            duration_ms=plan_res.latency_ms,
        )

        if not plan_res.text:
            return AnalyzerOutcome(
                status="failed",
                failure_reason="Empty response in plan generation phase",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        try:
            plan_payload = json.loads(plan_res.text)
        except Exception as exc:
            return AnalyzerOutcome(
                status="failed",
                failure_reason=f"Invalid JSON in plan generation response: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        if not isinstance(plan_payload, dict):
            return AnalyzerOutcome(
                status="failed",
                failure_reason="Plan response is not a JSON object",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        try:
            audit_plan = AuditPlan.from_agent_payload(plan_payload)
        except Exception as exc:
            return AnalyzerOutcome(
                status="failed",
                failure_reason=f"Invalid audit plan payload: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        # ==========================================
        # PHASE 2: Tool-calling exploration loop
        # ==========================================
        initial_user_msg = (
            f"Assess release readiness for repository {repository_url} "
            f"at ref {resolved_ref.requested_ref} (commit {resolved_ref.commit_sha}).\n\n"
            f"Your audit plan:\n{json.dumps(audit_plan.model_dump(), indent=2)}\n\n"
            f"{self._format_deterministic_checks()}\n\n"
            "Use the read-only inspection tools to gather evidence for your plan, preferring "
            "the deterministic evidence above over your own inference."
        )
        messages: list[Message] = [Message(role="user", content=initial_user_msg)]

        tool_specs = build_tool_specs()

        for turn_idx in range(1, self.max_turns + 1):
            if (time.time() - start_time) > self.deadline_s:
                return AnalyzerOutcome(
                    status="failed",
                    failure_reason="timeout",
                    usage_prompt_tokens=prompt_tokens,
                    usage_output_tokens=output_tokens,
                    usage_total_tokens=total_tokens,
                    turns=turns_count,
                    audit_plan=audit_plan,
                )

            turns_count += 1
            try:
                llm_res = self.llm.generate(
                    system=system_prompt,
                    messages=messages,
                    tools=tool_specs,
                )
            except Exception as exc:
                return AnalyzerOutcome(
                    status="failed",
                    failure_reason=f"LLM generation failed in turn {turn_idx}: {exc}",
                    usage_prompt_tokens=prompt_tokens,
                    usage_output_tokens=output_tokens,
                    usage_total_tokens=total_tokens,
                    turns=turns_count,
                    audit_plan=audit_plan,
                )

            prompt_tokens += llm_res.usage.prompt_tokens
            output_tokens += llm_res.usage.output_tokens
            total_tokens += llm_res.usage.total_tokens

            self.logger.log(
                component="analyzer",
                state="llm_generate",
                output_summary=llm_res.text or f"Generated {len(llm_res.tool_calls)} tool calls",
                duration_ms=llm_res.latency_ms,
            )

            if not llm_res.tool_calls:
                break

            messages.append(
                Message(
                    role="model",
                    content=llm_res.text,
                    tool_calls=llm_res.tool_calls,
                )
            )

            for tc in llm_res.tool_calls:
                tool_res = self.dispatcher.execute(tc)

                self.logger.log(
                    component="analyzer",
                    state="tool_execution",
                    tool=tc.name,
                    input_data=tc.args,
                    output_summary=str(tool_res.result)[:200] if tool_res.ok else str(tool_res.error)[:200],
                    evidence_created=tool_res.evidence_ids,
                    duration_ms=tool_res.duration_ms,
                    status="success" if tool_res.ok else "error",
                )

                tool_response = tool_res.result if tool_res.ok else {"error": tool_res.error}
                messages.append(
                    Message(
                        role="tool",
                        tool_name=tc.name,
                        tool_call_id=tc.call_id,
                        tool_response=tool_response,
                    )
                )

        # ==========================================
        # PHASE 3: Schema-constrained findings generation
        # ==========================================
        if (time.time() - start_time) > self.deadline_s:
            return AnalyzerOutcome(
                status="failed",
                failure_reason="timeout",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        turns_count += 1

        messages.append(
            Message(
                role="user",
                content="Please provide the final findings list based on your investigation.",
            )
        )

        try:
            final_res = self.llm.generate(
                system=system_prompt,
                messages=messages,
                response_schema=FINDINGS_SCHEMA,
                tools=None,
            )
        except Exception as exc:
            return AnalyzerOutcome(
                status="failed",
                failure_reason=f"LLM final generation failed: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        prompt_tokens += final_res.usage.prompt_tokens
        output_tokens += final_res.usage.output_tokens
        total_tokens += final_res.usage.total_tokens

        self.logger.log(
            component="analyzer",
            state="final_generation",
            output_summary=final_res.text[:200] if final_res.text else "Empty response",
            duration_ms=final_res.latency_ms,
        )

        if not final_res.text:
            return AnalyzerOutcome(
                status="failed",
                failure_reason="Empty response in final generation phase",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        try:
            payload = json.loads(final_res.text)
        except Exception as exc:
            return AnalyzerOutcome(
                status="failed",
                failure_reason=f"Invalid JSON in final generation response: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        if not isinstance(payload, dict):
            return AnalyzerOutcome(
                status="failed",
                failure_reason="Final response is not a JSON object",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        findings_val = payload.get("findings")
        if not isinstance(findings_val, list):
            return AnalyzerOutcome(
                status="failed",
                failure_reason="Missing or invalid findings list",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
                audit_plan=audit_plan,
            )

        accepted: list[Finding] = []
        rejected: list[dict] = []

        for idx, raw_finding in enumerate(findings_val, start=1):
            if not isinstance(raw_finding, dict):
                rejected.append({"finding": raw_finding, "reason": "not_an_object"})
                continue

            finding_data = redact_obj(dict(raw_finding))
            finding_data.setdefault("id", f"F-{idx:03d}")
            finding_data["audit_run_id"] = audit_run_id
            finding_data["verification_status"] = VerificationStatus.pending
            finding_data["origin"] = "analyzer"

            try:
                finding = Finding.model_validate(finding_data)
            except Exception as exc:
                rejected.append({"finding": redact_obj(raw_finding), "reason": f"invalid_finding_schema: {exc}"})
                continue

            if finding.severity == Severity.critical and not finding.evidence_ids:
                rejected.append(
                    {"finding": finding.model_dump(), "reason": "no_evidence_for_critical"}
                )
                continue

            hallucinated = [
                eid for eid in finding.evidence_ids if self.evidence_store.get(eid) is None
            ]
            if hallucinated:
                rejected.append(
                    {
                        "finding": finding.model_dump(),
                        "reason": "no_evidence_for_critical"
                        if finding.severity == Severity.critical
                        else f"unknown_evidence_ids: {hallucinated}",
                    }
                )
                continue

            accepted.append(finding)

        return AnalyzerOutcome(
            status="success",
            failure_reason=None,
            usage_prompt_tokens=prompt_tokens,
            usage_output_tokens=output_tokens,
            usage_total_tokens=total_tokens,
            turns=turns_count,
            audit_plan=audit_plan,
            findings=accepted,
            rejected_findings=rejected,
        )
