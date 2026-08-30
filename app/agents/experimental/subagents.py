# path: app/agents/experimental/subagents.py
"""It5 "removed experiment" (ТЗ Improvement Changelog): three specialized LLM subagents
(CI / Security / Test) as an alternative to the single Analyzer agent.

Hypothesis under test: specialization improves recall. This module implements and wires the
executed `it5_subagents` ablation (see
`app.orchestration.runner.AuditRunner._run_final_pipeline`). It is retained as a removed
experiment: the measured comparison is stored under `submission/results/ablations/` and the
default production path remains the single Analyzer.

Each subagent (`CategorySubagent`) follows the exact same 3-phase pattern as
`app.agents.analyzer.AnalyzerAgent` (forced plan -> tool-calling exploration loop seeded with
deterministic checks -> schema-constrained findings), just scoped to a single
`FindingCategory`. `run_it5_subagents` runs all three sequentially (this codebase has no
async/threading anywhere, so we keep that consistent) and combines their output into a single
`AnalyzerOutcome`, the same shape the rest of the orchestration pipeline already consumes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.agents.analyzer import FINDINGS_SCHEMA, PLAN_SCHEMA, AnalyzerOutcome
from app.evidence.store import EvidenceStore
from app.llm.types import LLMClient, Message
from app.security.redaction import redact_obj
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import FindingCategory, Severity, VerificationStatus
from app.schemas.findings import Finding
from app.schemas.plan import AuditPlan
from app.sources.base import RepositorySource, ResolvedRef
from app.tools.dispatch import ToolDispatcher
from app.tools.registry import build_tool_specs
from app.trajectory.logger import TrajectoryLogger


PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

# Category -> default prompt file, for the three categories It5 actually specializes in.
_CATEGORY_PROMPT_FILENAMES: dict[FindingCategory, str] = {
    FindingCategory.ci: "subagent_ci.md",
    FindingCategory.security: "subagent_security.md",
    FindingCategory.tests: "subagent_test.md",
}


class CategorySubagent:
    """A single-category specialized analyzer: same 3-phase pattern as AnalyzerAgent, but
    every accepted finding is enforced to belong to exactly one `FindingCategory`.

    Policy for off-scope findings: the model is still shown the full findings schema (so it
    can describe what it saw honestly), but any finding whose parsed `category` does not match
    this subagent's assigned category is REJECTED (not coerced) into `rejected_findings` with
    reason `"category_mismatch"`. Coercing would silently misattribute an off-scope claim to
    this subagent's category, which defeats the point of specialization (each subagent should
    only ever speak for its own area) and would make the It5 vs. Analyzer comparison harder to
    read honestly.
    """

    def __init__(
        self,
        llm: LLMClient,
        source: RepositorySource,
        dispatcher: ToolDispatcher,
        evidence_store: EvidenceStore,
        logger: TrajectoryLogger,
        category: FindingCategory,
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
        self.category = category
        self.deterministic_checks = deterministic_checks or []
        self.max_turns = max_turns
        self.deadline_s = deadline_s
        default_filename = _CATEGORY_PROMPT_FILENAMES.get(category)
        self.prompt_path = prompt_path or (
            PROMPTS_DIR / default_filename if default_filename else PROMPTS_DIR / "analyzer.md"
        )
        self._component = f"subagent_{category.value}"

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return (
            f"Assess whether this repository is ready for release, reporting only on "
            f"category '{self.category.value}'. Build a plan, gather evidence via read-only "
            "tools, and report findings in that category only."
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
            f"Build an audit plan scoped to category '{self.category.value}' for repository "
            f"{repository_url} at ref {resolved_ref.requested_ref} "
            f"(commit {resolved_ref.commit_sha}). "
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
            component=self._component,
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
            f"Assess release readiness for repository {repository_url} at ref "
            f"{resolved_ref.requested_ref} (commit {resolved_ref.commit_sha}), reporting only "
            f"on category '{self.category.value}'.\n\n"
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
                component=self._component,
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
                    component=self._component,
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
                content=(
                    f"Please provide the final findings list based on your investigation. "
                    f"Report only findings in category '{self.category.value}'."
                ),
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
            component=self._component,
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

            # Specialization enforcement: this subagent only ever speaks for its own category.
            # An off-scope finding is rejected outright rather than coerced, so It5's per-category
            # attribution stays honest (see class docstring for rationale).
            if finding.category != self.category:
                rejected.append(
                    {"finding": finding.model_dump(), "reason": "category_mismatch"}
                )
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


def CiSubagent(
    llm: LLMClient,
    source: RepositorySource,
    dispatcher: ToolDispatcher,
    evidence_store: EvidenceStore,
    logger: TrajectoryLogger,
    deterministic_checks: list[DeterministicCheckResult] | None = None,
    max_turns: int = 10,
    deadline_s: int = 300,
    prompt_path: Path | None = None,
) -> CategorySubagent:
    return CategorySubagent(
        llm=llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=evidence_store,
        logger=logger,
        category=FindingCategory.ci,
        deterministic_checks=deterministic_checks,
        max_turns=max_turns,
        deadline_s=deadline_s,
        prompt_path=prompt_path,
    )


def SecuritySubagent(
    llm: LLMClient,
    source: RepositorySource,
    dispatcher: ToolDispatcher,
    evidence_store: EvidenceStore,
    logger: TrajectoryLogger,
    deterministic_checks: list[DeterministicCheckResult] | None = None,
    max_turns: int = 10,
    deadline_s: int = 300,
    prompt_path: Path | None = None,
) -> CategorySubagent:
    return CategorySubagent(
        llm=llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=evidence_store,
        logger=logger,
        category=FindingCategory.security,
        deterministic_checks=deterministic_checks,
        max_turns=max_turns,
        deadline_s=deadline_s,
        prompt_path=prompt_path,
    )


def TestSubagent(
    llm: LLMClient,
    source: RepositorySource,
    dispatcher: ToolDispatcher,
    evidence_store: EvidenceStore,
    logger: TrajectoryLogger,
    deterministic_checks: list[DeterministicCheckResult] | None = None,
    max_turns: int = 10,
    deadline_s: int = 300,
    prompt_path: Path | None = None,
) -> CategorySubagent:
    return CategorySubagent(
        llm=llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=evidence_store,
        logger=logger,
        category=FindingCategory.tests,
        deterministic_checks=deterministic_checks,
        max_turns=max_turns,
        deadline_s=deadline_s,
        prompt_path=prompt_path,
    )


def build_subagents(
    llm: LLMClient,
    source: RepositorySource,
    dispatcher: ToolDispatcher,
    evidence_store: EvidenceStore,
    logger: TrajectoryLogger,
    deterministic_checks: list[DeterministicCheckResult] | None = None,
    max_turns: int = 10,
    deadline_s: int = 300,
) -> list[CategorySubagent]:
    """Factory for all three It5 subagents, in the fixed order they run in."""
    kwargs: dict[str, Any] = dict(
        llm=llm,
        source=source,
        dispatcher=dispatcher,
        evidence_store=evidence_store,
        logger=logger,
        deterministic_checks=deterministic_checks,
        max_turns=max_turns,
        deadline_s=deadline_s,
    )
    return [
        CiSubagent(**kwargs),
        SecuritySubagent(**kwargs),
        TestSubagent(**kwargs),
    ]


def run_it5_subagents(
    llm: LLMClient,
    source: RepositorySource,
    dispatcher: ToolDispatcher,
    evidence_store: EvidenceStore,
    logger: TrajectoryLogger,
    deterministic_checks: list[DeterministicCheckResult] | None,
    repository_url: str,
    resolved_ref: ResolvedRef,
    audit_run_id: str,
    max_turns: int = 10,
    deadline_s: int = 300,
) -> AnalyzerOutcome:
    """Run the CI / Security / Test subagents sequentially and combine their output into a
    single `AnalyzerOutcome`, the same shape `_run_final_pipeline` already consumes from the
    single Analyzer.

    Budgeting: the shared `deadline_s` is tracked as elapsed wall-clock across the three
    sequential calls, and each subagent is given only the remaining budget — NOT the full
    `deadline_s` each — so It5 cannot legitimately take ~3x longer than the single-Analyzer
    path. That runtime cost is exactly one of the things this experiment needs to measure
    honestly.

    Failure handling: a hard failure (status != "success") in ANY subagent is not silently
    swallowed. All three subagents still run (so a later subagent's independent failure isn't
    hidden by an earlier one), but if any failed, the combined outcome is `status="failed"`
    with a `failure_reason` that concatenates every subagent's failure — mirroring how a single
    Analyzer's phase-1 failure is already treated as fatal for the whole run.
    """
    start_time = time.time()

    total_prompt_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_turns = 0
    all_findings: list[Finding] = []
    all_rejected: list[dict] = []
    failure_reasons: list[str] = []

    subagent_factories = [
        ("ci", CiSubagent),
        ("security", SecuritySubagent),
        ("tests", TestSubagent),
    ]

    for label, factory in subagent_factories:
        elapsed = time.time() - start_time
        remaining_budget = max(deadline_s - elapsed, 0)

        subagent = factory(
            llm=llm,
            source=source,
            dispatcher=dispatcher,
            evidence_store=evidence_store,
            logger=logger,
            deterministic_checks=deterministic_checks,
            max_turns=max_turns,
            deadline_s=remaining_budget,
        )
        outcome = subagent.run(
            repository_url=repository_url,
            resolved_ref=resolved_ref,
            audit_run_id=audit_run_id,
        )

        total_prompt_tokens += outcome.usage_prompt_tokens
        total_output_tokens += outcome.usage_output_tokens
        total_tokens += outcome.usage_total_tokens
        total_turns += outcome.turns

        if outcome.status != "success":
            failure_reasons.append(
                f"{label} subagent failed: {outcome.failure_reason or 'unknown reason'}"
            )
            continue

        all_findings.extend(outcome.findings)
        all_rejected.extend(outcome.rejected_findings)

    if failure_reasons:
        return AnalyzerOutcome(
            status="failed",
            failure_reason="; ".join(failure_reasons),
            usage_prompt_tokens=total_prompt_tokens,
            usage_output_tokens=total_output_tokens,
            usage_total_tokens=total_tokens,
            turns=total_turns,
        )

    # Renumber sequentially across the combined set (F-001, F-002, ...) to avoid collisions
    # between subagents that each independently numbered their own findings from F-001.
    # evidence_ids point at Evidence objects (not other findings), so they are untouched.
    renumbered_findings: list[Finding] = [
        finding.model_copy(update={"id": f"F-{idx:03d}"})
        for idx, finding in enumerate(all_findings, start=1)
    ]

    return AnalyzerOutcome(
        status="success",
        failure_reason=None,
        usage_prompt_tokens=total_prompt_tokens,
        usage_output_tokens=total_output_tokens,
        usage_total_tokens=total_tokens,
        turns=total_turns,
        audit_plan=None,
        findings=renumbered_findings,
        rejected_findings=all_rejected,
    )
