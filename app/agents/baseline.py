# path: app/agents/baseline.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.store import EvidenceStore
from app.llm.types import LLMClient, Message, ToolCall
from app.schemas.enums import Decision, FindingCategory, Severity
from app.sources.base import RepositorySource, ResolvedRef
from app.tools.dispatch import ToolDispatcher
from app.tools.registry import build_tool_specs
from app.trajectory.logger import TrajectoryLogger


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["GO", "REVIEW", "NO-GO"],
            "description": "Release decision",
        },
        "executive_summary": {
            "type": "string",
            "description": "Executive summary of audit findings and readiness decision",
        },
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
    "required": ["decision", "executive_summary", "findings"],
}


class BaselineOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings_payload: dict | None = None
    status: Literal["success", "failed"]
    failure_reason: str | None = None
    usage_prompt_tokens: int = 0
    usage_output_tokens: int = 0
    usage_total_tokens: int = 0
    turns: int = 0


class BaselineAgent:
    """Official baseline agent B1 with two-phase execution."""

    def __init__(
        self,
        llm: LLMClient,
        source: RepositorySource,
        dispatcher: ToolDispatcher,
        evidence_store: EvidenceStore,
        logger: TrajectoryLogger,
        max_turns: int = 10,
        deadline_s: int = 300,
        prompt_path: Path | None = None,
    ) -> None:
        self.llm = llm
        self.source = source
        self.dispatcher = dispatcher
        self.evidence_store = evidence_store
        self.logger = logger
        self.max_turns = max_turns
        self.deadline_s = deadline_s
        self.prompt_path = prompt_path or (PROMPTS_DIR / "baseline.md")

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return "Assess whether this repository is ready for release. Identify blockers and explain the risks."

    def run(
        self,
        repository_url: str,
        resolved_ref: ResolvedRef,
        audit_run_id: str,
    ) -> BaselineOutcome:
        start_time = time.time()
        system_prompt = self._load_prompt()
        prompt_tokens = 0
        output_tokens = 0
        total_tokens = 0
        turns_count = 0

        initial_user_msg = (
            f"Assess release readiness for repository {repository_url} "
            f"at ref {resolved_ref.requested_ref} (commit {resolved_ref.commit_sha})."
        )
        messages: list[Message] = [Message(role="user", content=initial_user_msg)]

        tool_specs = build_tool_specs()

        # ==========================================
        # PHASE 1: Tool-calling exploration loop
        # ==========================================
        for turn_idx in range(1, self.max_turns + 1):
            if (time.time() - start_time) > self.deadline_s:
                return BaselineOutcome(
                    status="failed",
                    failure_reason="timeout",
                    usage_prompt_tokens=prompt_tokens,
                    usage_output_tokens=output_tokens,
                    usage_total_tokens=total_tokens,
                    turns=turns_count,
                )

            turns_count += 1
            try:
                llm_res = self.llm.generate(
                    system=system_prompt,
                    messages=messages,
                    tools=tool_specs,
                )
            except Exception as exc:
                return BaselineOutcome(
                    status="failed",
                    failure_reason=f"LLM generation failed in turn {turn_idx}: {exc}",
                    usage_prompt_tokens=prompt_tokens,
                    usage_output_tokens=output_tokens,
                    usage_total_tokens=total_tokens,
                    turns=turns_count,
                )

            prompt_tokens += llm_res.usage.prompt_tokens
            output_tokens += llm_res.usage.output_tokens
            total_tokens += llm_res.usage.total_tokens

            self.logger.log(
                component="baseline",
                state="llm_generate",
                output_summary=llm_res.text or f"Generated {len(llm_res.tool_calls)} tool calls",
                duration_ms=llm_res.latency_ms,
            )

            # If no tool calls, exploration phase is complete
            if not llm_res.tool_calls:
                break

            messages.append(
                Message(
                    role="model",
                    content=llm_res.text,
                    tool_calls=llm_res.tool_calls,
                )
            )

            # Execute every tool call requested
            for tc in llm_res.tool_calls:
                tool_res = self.dispatcher.execute(tc)

                self.logger.log(
                    component="baseline",
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
        # PHASE 2: Schema-constrained final generation
        # ==========================================
        if (time.time() - start_time) > self.deadline_s:
            return BaselineOutcome(
                status="failed",
                failure_reason="timeout",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        turns_count += 1

        # Explicit neutral instruction to request final readiness evaluation
        messages.append(
            Message(
                role="user",
                content="Please provide the final release readiness evaluation and decision based on your findings.",
            )
        )

        try:
            final_res = self.llm.generate(
                system=system_prompt,
                messages=messages,
                response_schema=FINAL_SCHEMA,
                tools=None,
            )
        except Exception as exc:
            return BaselineOutcome(
                status="failed",
                failure_reason=f"LLM final generation failed: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        prompt_tokens += final_res.usage.prompt_tokens
        output_tokens += final_res.usage.output_tokens
        total_tokens += final_res.usage.total_tokens

        self.logger.log(
            component="baseline",
            state="final_generation",
            output_summary=final_res.text[:200] if final_res.text else "Empty response",
            duration_ms=final_res.latency_ms,
        )

        if not final_res.text:
            return BaselineOutcome(
                status="failed",
                failure_reason="Empty response in final generation phase",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        try:
            payload = json.loads(final_res.text)
        except Exception as exc:
            return BaselineOutcome(
                status="failed",
                failure_reason=f"Invalid JSON in final generation response: {exc}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        # Validate schema structure
        if not isinstance(payload, dict):
            return BaselineOutcome(
                status="failed",
                failure_reason="Final response is not a JSON object",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        decision_val = payload.get("decision")
        if decision_val not in ("GO", "REVIEW", "NO-GO"):
            return BaselineOutcome(
                status="failed",
                failure_reason=f"Invalid decision value: {decision_val}",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        if "executive_summary" not in payload or not isinstance(payload["executive_summary"], str):
            return BaselineOutcome(
                status="failed",
                failure_reason="Missing or invalid executive_summary",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        findings_val = payload.get("findings")
        if not isinstance(findings_val, list):
            return BaselineOutcome(
                status="failed",
                failure_reason="Missing or invalid findings list",
                usage_prompt_tokens=prompt_tokens,
                usage_output_tokens=output_tokens,
                usage_total_tokens=total_tokens,
                turns=turns_count,
            )

        return BaselineOutcome(
            findings_payload=payload,
            status="success",
            failure_reason=None,
            usage_prompt_tokens=prompt_tokens,
            usage_output_tokens=output_tokens,
            usage_total_tokens=total_tokens,
            turns=turns_count,
        )
