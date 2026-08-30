# path: app/agents/verifier.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.evidence.store import EvidenceStore
from app.llm.types import LLMClient, Message, Usage
from app.security.redaction import redact, redact_obj
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import VerifierStatus
from app.schemas.findings import Finding
from app.schemas.verification import VerificationResult
from app.sources.base import RepositorySource
from app.tools.dispatch import ToolDispatcher
from app.tools.registry import build_tool_specs
from app.trajectory.logger import TrajectoryLogger


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "finding_id": {
            "type": "string",
            "description": "The id of the finding being verified. Must match exactly.",
        },
        "status": {
            "type": "string",
            "enum": ["confirmed", "rejected", "uncertain"],
            "description": "Verification verdict",
        },
        "confidence": {
            "type": "number",
            "description": "Verifier's own confidence in this verdict, 0.0-1.0",
        },
        "supporting_evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence ids that support the original claim",
        },
        "contradicting_evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence ids that contradict the original claim",
        },
        "reason_summary": {
            "type": "string",
            "description": "Concise explanation of the verdict grounded in evidence",
        },
    },
    "required": [
        "finding_id",
        "status",
        "confidence",
        "supporting_evidence",
        "contradicting_evidence",
        "reason_summary",
    ],
}


def _forced_uncertain(finding_id: str, reason: str) -> VerificationResult:
    """Build the mandatory failure-path result: always uncertain, always carries verifier_error."""
    return VerificationResult(
        finding_id=finding_id,
        status=VerifierStatus.uncertain,
        confidence=0.0,
        supporting_evidence=[],
        contradicting_evidence=[],
        reason_summary=f"verifier_failed: {reason}",
        verifier_error=reason,
    )


class VerifierAgent:
    """Adversarial single-finding verifier.

    Verifies exactly ONE finding per `verify()` call. The orchestrator is responsible
    for looping over the set of findings that require verification and for enforcing
    any cross-finding time budget.

    Token usage for the most recent `verify()` call is exposed via `self.last_usage`
    (a fresh `Usage()` at the start of each call) so the orchestrator can fold verifier
    cost into the overall audit's token/cost accounting.
    """

    def __init__(
        self,
        llm: LLMClient,
        source: RepositorySource,
        dispatcher: ToolDispatcher,
        evidence_store: EvidenceStore,
        logger: TrajectoryLogger,
        deterministic_checks: list[DeterministicCheckResult] | None = None,
        max_extra_tool_calls: int = 2,
        deadline_s: int = 300,
        prompt_path: Path | None = None,
    ) -> None:
        self.llm = llm
        self.source = source
        self.dispatcher = dispatcher
        self.evidence_store = evidence_store
        self.logger = logger
        self.deterministic_checks = deterministic_checks or []
        self.max_extra_tool_calls = max_extra_tool_calls
        self.deadline_s = deadline_s
        self.prompt_path = prompt_path or (PROMPTS_DIR / "verifier.md")
        self.last_usage = Usage()

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return (
            "Attempt to falsify the given finding using only the evidence provided. "
            "Never introduce a new finding. Use 'uncertain' for genuine ambiguity."
        )

    def _build_initial_message(self, finding: Finding) -> str:
        finding_payload = finding.model_dump(
            mode="json",
            include={
                "id",
                "category",
                "title",
                "severity",
                "claim",
                "confidence",
                "evidence_ids",
                "recommended_action",
            },
        )

        evidence_items: list[dict[str, Any]] = []
        for eid in finding.evidence_ids:
            ev = self.evidence_store.get(eid)
            if ev is None:
                evidence_items.append({"id": eid, "error": "evidence_not_found"})
                continue
            evidence_items.append(
                {
                    "id": ev.id,
                    "source_path": ev.source_path,
                    "source_ref": ev.source_ref,
                    "summary": ev.summary,
                    "payload": ev.payload,
                    "line_start": ev.line_start,
                    "line_end": ev.line_end,
                }
            )

        checks_payload = [c.model_dump(mode="json") for c in self.deterministic_checks]

        body = {
            "finding": finding_payload,
            "cited_evidence": evidence_items,
            "deterministic_checks": checks_payload,
        }

        return (
            "Verify the following finding. Try to falsify the claim and actively look "
            "for contradicting evidence. You were not shown the analyst's reasoning — "
            "only the finding and the evidence below.\n\n" + json.dumps(body, ensure_ascii=False)
        )

    def verify(self, finding: Finding, audit_run_id: str) -> VerificationResult:
        start_time = time.time()
        system_prompt = self._load_prompt()
        tool_specs = build_tool_specs()

        prompt_tokens = 0
        output_tokens = 0
        total_tokens = 0

        def finish(result: VerificationResult) -> VerificationResult:
            self.last_usage = Usage(
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
            return result

        messages: list[Message] = [Message(role="user", content=self._build_initial_message(finding))]

        # ==========================================
        # PHASE 1: bounded tool-calling loop (up to max_extra_tool_calls turns)
        # ==========================================
        for turn_idx in range(1, self.max_extra_tool_calls + 1):
            if (time.time() - start_time) > self.deadline_s:
                return finish(_forced_uncertain(finding.id, "timeout"))

            try:
                llm_res = self.llm.generate(
                    system=system_prompt,
                    messages=messages,
                    tools=tool_specs,
                )
            except Exception as exc:
                return finish(
                    _forced_uncertain(finding.id, f"LLM generation failed in tool turn {turn_idx}: {exc}")
                )

            prompt_tokens += llm_res.usage.prompt_tokens
            output_tokens += llm_res.usage.output_tokens
            total_tokens += llm_res.usage.total_tokens

            self.logger.log(
                component="verifier",
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
                    component="verifier",
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
        # PHASE 2: schema-constrained final verdict
        # ==========================================
        if (time.time() - start_time) > self.deadline_s:
            return finish(_forced_uncertain(finding.id, "timeout"))

        messages.append(
            Message(
                role="user",
                content=(
                    "Provide your final verification verdict now, in the required "
                    "structured format. Do not introduce any new finding."
                ),
            )
        )

        try:
            final_res = self.llm.generate(
                system=system_prompt,
                messages=messages,
                response_schema=VERIFICATION_SCHEMA,
                tools=None,
            )
        except Exception as exc:
            return finish(_forced_uncertain(finding.id, f"LLM final generation failed: {exc}"))

        prompt_tokens += final_res.usage.prompt_tokens
        output_tokens += final_res.usage.output_tokens
        total_tokens += final_res.usage.total_tokens

        self.logger.log(
            component="verifier",
            state="final_generation",
            output_summary=final_res.text[:200] if final_res.text else "Empty response",
            duration_ms=final_res.latency_ms,
        )

        if not final_res.text:
            return finish(_forced_uncertain(finding.id, "Empty response in final generation phase"))

        try:
            payload = json.loads(final_res.text)
        except Exception as exc:
            return finish(_forced_uncertain(finding.id, f"Invalid JSON in final verification response: {exc}"))

        if not isinstance(payload, dict):
            return finish(_forced_uncertain(finding.id, "Final verification response is not a JSON object"))

        returned_finding_id = payload.get("finding_id")
        if returned_finding_id != finding.id:
            return finish(
                _forced_uncertain(
                    finding.id,
                    f"finding_id mismatch: model returned {returned_finding_id!r}, expected {finding.id!r}",
                )
            )
        payload = redact_obj(payload)

        try:
            result = VerificationResult(
                finding_id=finding.id,
                status=payload.get("status"),
                confidence=payload.get("confidence"),
                supporting_evidence=payload.get("supporting_evidence", []),
                contradicting_evidence=payload.get("contradicting_evidence", []),
                reason_summary=redact(payload.get("reason_summary")),
            )
        except ValidationError as exc:
            return finish(_forced_uncertain(finding.id, f"Schema validation failed: {exc}"))

        return finish(result)
