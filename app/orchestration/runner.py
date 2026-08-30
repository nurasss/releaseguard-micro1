# path: app/orchestration/runner.py
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.analyzer import AnalyzerAgent
from app.agents.baseline import BaselineAgent
from app.agents.experimental.subagents import run_it5_subagents
from app.agents.verifier import VerifierAgent
from app.checks.registry import run_all_checks
from app.config import Settings, get_settings
from app.evidence.store import EvidenceStore
from app.llm.gemini import GeminiClient
from app.llm.offline import OfflineFixtureLLM
from app.llm.pricing import estimate_cost_usd
from app.llm.types import LLMClient, Usage
from app.policy.decision import decide
from app.reports.markdown import render_report_md
from app.security.redaction import redact
from app.schemas.audit import AuditRun, DeterministicCheckResult
from app.schemas.enums import (
    Decision,
    FindingCategory,
    RunStatus,
    Severity,
    VerificationStatus,
    VerifierStatus,
)
from app.schemas.findings import Finding
from app.schemas.integrity import IntegrityViolation, validate_report_integrity
from app.schemas.report import AuditReport
from app.schemas.verification import VerificationResult
from app.sources.base import RepositorySource, ResolvedRef
from app.sources.errors import PrivateRepositoryError, SourceError, UnknownRefError
from app.sources.fixture import LocalFixtureSource
from app.sources.github import GitHubSource
from app.sources.snapshot import SnapshotManager
from app.storage.db import connect, init_db
from app.storage.repository import AuditRepository
from app.tools.dispatch import ToolDispatcher
from app.trajectory.logger import TrajectoryLogger


class RunOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: AuditRun
    report: AuditReport
    artifacts_dir: Path
    integrity_violations: list[IntegrityViolation] = Field(default_factory=list)


AblationName = Literal[
    "none",
    "no_verifier",
    "no_evidence_enforcement",
    "no_deterministic_checks",
    "no_tool_output_normalization",
    "it5_subagents",
]


def _generate_audit_run_id(
    repository_url: str,
    ref: str,
    mode: str,
    timestamp: str,
) -> str:
    seed = f"{repository_url}|{ref}|{mode}|{timestamp}".encode("utf-8")
    hex_digest = hashlib.sha256(seed).hexdigest()[:12]
    return f"aud_{hex_digest}"


class AuditRunner:
    """Orchestrates end-to-end repository audits and persistence."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm_factory: Callable[[], LLMClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_factory = llm_factory

    def _get_llm(
        self,
        source: RepositorySource | None = None,
        dispatcher: ToolDispatcher | None = None,
        evidence_store: EvidenceStore | None = None,
        mode: str = "final",
    ) -> LLMClient:
        if self.llm_factory is not None:
            return self.llm_factory()
        if self.settings.offline_mode:
            if source is None or dispatcher is None or evidence_store is None:
                raise ValueError("offline mode requires source, dispatcher, and evidence_store")
            return OfflineFixtureLLM(
                source=source,
                dispatcher=dispatcher,
                evidence_store=evidence_store,
                mode=mode,
            )
        return GeminiClient(
            api_key=self.settings.api_key or "",
            model_id=self.settings.model_id,
            timeout_s=self.settings.request_timeout_s,
            max_retries=self.settings.max_retries,
            min_request_interval_ms=self.settings.min_request_interval_ms,
        )

    def run_case(
        self,
        case_dir: Path | str,
        mode: Literal["baseline", "final"] = "baseline",
        timestamp: str | None = None,
        max_turns: int | None = None,
        ablation: AblationName = "none",
    ) -> RunOutcome:
        case_path = Path(case_dir).resolve()
        case_meta_file = case_path / "case.json"

        if case_meta_file.exists():
            meta = json.loads(case_meta_file.read_text(encoding="utf-8"))
            repo_url = meta.get("repository_url", f"https://github.com/eval/{case_path.name}")
            requested_ref = meta.get("requested_ref", "main")
        else:
            repo_url = f"https://github.com/eval/{case_path.name}"
            requested_ref = "main"

        source = LocalFixtureSource(case_path)
        return self._execute_audit(
            source=source,
            repository_url=repo_url,
            ref=requested_ref,
            mode=mode,
            timestamp=timestamp,
            max_turns=max_turns,
            ablation=ablation,
        )

    def run_repository(
        self,
        repository_url: str,
        ref: str,
        mode: Literal["baseline", "final"] = "baseline",
        timestamp: str | None = None,
        max_turns: int | None = None,
        ablation: AblationName = "none",
    ) -> RunOutcome:
        source = GitHubSource(
            repo_url=repository_url,
            token=self.settings.github_token,
        )
        # Surface the policy violation to the HTTP/API caller as a rejected
        # request. `_execute_audit` repeats the guard for direct callers and
        # local fixtures, but no repository content is fetched here.
        if bool(source.get_repository_metadata().get("private", False)):
            raise PrivateRepositoryError(
                "Private repositories are not supported; audit a public repository snapshot instead."
            )
        return self._execute_audit(
            source=source,
            repository_url=repository_url,
            ref=ref,
            mode=mode,
            timestamp=timestamp,
            max_turns=max_turns,
            ablation=ablation,
        )

    def _execute_audit(
        self,
        source: RepositorySource,
        repository_url: str,
        ref: str,
        mode: Literal["baseline", "final"],
        timestamp: str | None,
        max_turns: int | None = None,
        ablation: AblationName = "none",
    ) -> RunOutcome:
        start_wall_time = time.time()
        start_ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        audit_run_id = _generate_audit_run_id(
            repository_url=repository_url,
            ref=ref,
            mode=mode,
            timestamp=start_ts,
        )

        run_artifacts_dir = (self.settings.data_dir / audit_run_id).resolve()
        run_artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 1. Reject private targets before resolving or exposing repository data.
        commit_sha = ""
        try:
            metadata = source.get_repository_metadata()
            if bool(metadata.get("private", False)):
                raise PrivateRepositoryError(
                    "Private repositories are not supported; audit a public repository snapshot instead."
                )
            resolved_ref = source.resolve_ref(ref)
            commit_sha = resolved_ref.commit_sha
        except (UnknownRefError, SourceError) as exc:
            # Handle ref resolution failure cleanly
            finish_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            runtime_ms = int((time.time() - start_wall_time) * 1000)

            run_fail = AuditRun(
                id=audit_run_id,
                repository_url=repository_url,
                requested_ref=ref,
                commit_sha="0" * 40,
                status=RunStatus.failed,
                final_decision=Decision.REVIEW,
                started_at=start_ts,
                finished_at=finish_ts,
                runtime_ms=runtime_ms,
                estimated_cost_usd=0.0,
                model_id=self.settings.model_id,
                prompt_version=self.settings.prompt_version,
                system_version=self.settings.system_version,
                mode=mode,
                ablation=ablation,
            )

            report_fail = AuditReport(
                audit_run_id=audit_run_id,
                repository_url=repository_url,
                requested_ref=ref,
                commit_sha="0" * 40,
                mode=mode,
                decision=Decision.REVIEW,
                executive_summary=f"Ref resolution failed for {ref!r}: {exc}",
                findings=[],
                verifications=[],
                evidence=[],
                deterministic_checks=[],
                limitations=[f"Audit uncompleted: ref resolution failed with error: {exc}"],
                runtime_ms=runtime_ms,
                model_id=self.settings.model_id,
                prompt_version=self.settings.prompt_version,
                estimated_cost_usd=0.0,
            )

            violations = validate_report_integrity(report_fail)

            # Persist failed run to SQLite and disk
            db_conn = connect(self.settings.db_path)
            init_db(db_conn)
            repo = AuditRepository(db_conn)
            repo.save_run(run_fail)
            db_conn.close()

            (run_artifacts_dir / "report.json").write_text(report_fail.model_dump_json(indent=2), encoding="utf-8")
            (run_artifacts_dir / "run.json").write_text(run_fail.model_dump_json(indent=2), encoding="utf-8")

            return RunOutcome(
                run=run_fail,
                report=report_fail,
                artifacts_dir=run_artifacts_dir,
                integrity_violations=violations,
            )

        # 2. Setup EvidenceStore, ToolDispatcher, TrajectoryLogger
        store = EvidenceStore(audit_run_id=audit_run_id, commit_sha=commit_sha)
        dispatcher = ToolDispatcher(
            source=source,
            evidence=store,
            normalize_outputs=ablation != "no_tool_output_normalization",
        )
        logger = TrajectoryLogger(audit_run_id=audit_run_id, trajectories_dir=self.settings.trajectories_dir)
        SnapshotManager().capture(
            source=source,
            repository_url=repository_url,
            requested_ref=ref,
            resolved_ref=resolved_ref,
            output_path=run_artifacts_dir / "snapshot.json",
        )

        # 3. Execute the mode-specific pipeline
        llm = self._get_llm(
            source=source,
            dispatcher=dispatcher,
            evidence_store=store,
            mode=mode,
        )
        limitations: list[str] = []
        rejected_findings: list[Finding] = []
        verifications: list[VerificationResult] = []
        deterministic_checks: list[DeterministicCheckResult] = []
        run_succeeded: bool

        if mode == "baseline":
            agent = BaselineAgent(
                llm=llm,
                source=source,
                dispatcher=dispatcher,
                evidence_store=store,
                logger=logger,
                max_turns=max_turns if max_turns is not None else 10,
                deadline_s=self.settings.audit_deadline_s,
            )

            outcome = agent.run(
                repository_url=repository_url,
                resolved_ref=resolved_ref,
                audit_run_id=audit_run_id,
            )

            findings: list[Finding] = []
            run_succeeded = outcome.status == "success"

            if run_succeeded and outcome.findings_payload:
                decision = Decision(outcome.findings_payload.get("decision", "REVIEW"))
                executive_summary = redact(outcome.findings_payload.get("executive_summary", ""))
                raw_findings = outcome.findings_payload.get("findings", [])

                for idx, rf in enumerate(raw_findings, start=1):
                    f_id = f"F-{idx:03d}"
                    findings.append(
                        Finding(
                            id=f_id,
                            audit_run_id=audit_run_id,
                            category=FindingCategory(rf["category"]),
                            title=redact(rf["title"]),
                            severity=Severity(rf["severity"]),
                            claim=redact(rf["claim"]),
                            confidence=float(rf["confidence"]),
                            evidence_ids=rf.get("evidence_ids", []),
                            recommended_action=redact(rf.get("recommended_action", "")),
                            verification_status=VerificationStatus.pending,
                            origin="baseline",
                        )
                    )
            else:
                decision = Decision.REVIEW
                executive_summary = f"Audit failed: {outcome.failure_reason or 'unknown reason'}"
                limitations.append(f"Audit incomplete: {outcome.failure_reason or 'Agent failed to produce result'}")

            usage_obj = Usage(
                prompt_tokens=outcome.usage_prompt_tokens,
                output_tokens=outcome.usage_output_tokens,
                total_tokens=outcome.usage_total_tokens,
            )

        else:
            (
                findings,
                rejected_findings,
                verifications,
                deterministic_checks,
                decision,
                executive_summary,
                run_succeeded,
                usage_obj,
                pipeline_limitations,
            ) = self._run_final_pipeline(
                llm=llm,
                source=source,
                dispatcher=dispatcher,
                store=store,
                logger=logger,
                resolved_ref=resolved_ref,
                repository_url=repository_url,
                audit_run_id=audit_run_id,
                start_wall_time=start_wall_time,
                max_turns=max_turns,
                ablation=ablation,
            )
            limitations.extend(pipeline_limitations)

        runtime_ms = int((time.time() - start_wall_time) * 1000)
        finish_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        report_model_id = getattr(llm, "model_id", self.settings.model_id)

        # 5. Estimate cost with full token breakdown
        cost_est = estimate_cost_usd(report_model_id, usage_obj)
        if cost_est is None:
            cost_usd = 0.0
            limitations.append(
                f"Model {report_model_id} pricing is not configured; "
                f"cost is tracked via tokens ({usage_obj.total_tokens} total tokens)"
            )
        else:
            cost_usd = cost_est

        # 6. Assemble AuditReport
        report = AuditReport(
            audit_run_id=audit_run_id,
            repository_url=repository_url,
            requested_ref=ref,
            commit_sha=commit_sha,
            mode=mode,
            decision=decision,
            executive_summary=executive_summary,
            findings=findings,
            rejected_findings=rejected_findings,
            verifications=verifications,
            evidence=store.all(),
            deterministic_checks=deterministic_checks,
            limitations=[redact(item) for item in limitations],
            runtime_ms=runtime_ms,
            model_id=report_model_id,
            prompt_version=self.settings.prompt_version,
            estimated_cost_usd=cost_usd,
        )

        # 7. Run integrity check (do NOT raise on violations)
        violations = validate_report_integrity(report)

        # 8. Assemble AuditRun
        run_status = RunStatus.completed if run_succeeded else RunStatus.failed
        audit_run = AuditRun(
            id=audit_run_id,
            repository_url=repository_url,
            requested_ref=ref,
            commit_sha=commit_sha,
            status=run_status,
            final_decision=decision,
            started_at=start_ts,
            finished_at=finish_ts,
            runtime_ms=runtime_ms,
            estimated_cost_usd=cost_usd,
            model_id=report_model_id,
            prompt_version=self.settings.prompt_version,
            system_version=self.settings.system_version,
            mode=mode,
            ablation=ablation,
        )

        # 9. Save to SQLite database
        db_conn = connect(self.settings.db_path)
        init_db(db_conn)
        repo = AuditRepository(db_conn)
        repo.save_run(audit_run)
        repo.save_evidence(report.evidence)
        repo.save_findings(report.findings + report.rejected_findings)
        for verification in report.verifications:
            repo.save_verification(verification, audit_run_id)
        for step in logger.steps():
            repo.save_agent_step(step)
        db_conn.close()

        # 10. Save artifacts to runs/<audit_run_id>/
        (run_artifacts_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (run_artifacts_dir / "run.json").write_text(audit_run.model_dump_json(indent=2), encoding="utf-8")
        (run_artifacts_dir / "report.md").write_text(render_report_md(report), encoding="utf-8")

        return RunOutcome(
            run=audit_run,
            report=report,
            artifacts_dir=run_artifacts_dir,
            integrity_violations=violations,
        )

    def _run_final_pipeline(
        self,
        llm: LLMClient,
        source: RepositorySource,
        dispatcher: ToolDispatcher,
        store: EvidenceStore,
        logger: TrajectoryLogger,
        resolved_ref: ResolvedRef,
        repository_url: str,
        audit_run_id: str,
        start_wall_time: float,
        max_turns: int | None,
        ablation: AblationName = "none",
    ) -> tuple[
        list[Finding],
        list[Finding],
        list[VerificationResult],
        list[DeterministicCheckResult],
        Decision,
        str,
        bool,
        Usage,
        list[str],
    ]:
        """Deterministic checks -> Analyzer -> Verifier -> Decision Policy (ТЗ §5-13).

        `ablation` isolates the contribution of individual components (ТЗ §27):
        - "no_verifier": skip the Verifier entirely, trust every critical/high finding
          as confirmed outright (isolates verification's effect on precision/unsupported-critical).
        - "no_evidence_enforcement": findings the Analyzer rejected ONLY for missing
          evidence on a critical claim are let back into the candidate pool.
        - "no_deterministic_checks": skip run_all_checks() entirely.
        - "no_tool_output_normalization": keep redaction and hard bounds, but send each
          tool result to the agent as a serialized payload instead of the normalized object.
        - "it5_subagents": It5 "removed experiment" (ТЗ Improvement Changelog) — runs three
          specialized subagents (CI / Security / Test) sequentially instead of the single
          Analyzer, and combines their output into one Analyzer-shaped outcome. See
          `app.agents.experimental.subagents.run_it5_subagents`.
        """
        limitations: list[str] = []
        deadline_s = self.settings.audit_deadline_s

        if ablation == "no_tool_output_normalization":
            limitations.append(
                "Ablation 'no_tool_output_normalization': tool results were sent as bounded "
                "redacted serialized payloads rather than normalized objects."
            )

        if ablation == "no_deterministic_checks":
            deterministic_checks: list[DeterministicCheckResult] = []
        else:
            deterministic_checks = run_all_checks(source, resolved_ref, store)

        if ablation == "it5_subagents":
            analyzer_outcome = run_it5_subagents(
                llm=llm,
                source=source,
                dispatcher=dispatcher,
                evidence_store=store,
                logger=logger,
                deterministic_checks=deterministic_checks,
                repository_url=repository_url,
                resolved_ref=resolved_ref,
                audit_run_id=audit_run_id,
                max_turns=max_turns if max_turns is not None else 10,
                deadline_s=deadline_s,
            )
        else:
            analyzer = AnalyzerAgent(
                llm=llm,
                source=source,
                dispatcher=dispatcher,
                evidence_store=store,
                logger=logger,
                deterministic_checks=deterministic_checks,
                max_turns=max_turns if max_turns is not None else 10,
                deadline_s=deadline_s,
            )
            analyzer_outcome = analyzer.run(
                repository_url=repository_url,
                resolved_ref=resolved_ref,
                audit_run_id=audit_run_id,
            )

        total_prompt_tokens = analyzer_outcome.usage_prompt_tokens
        total_output_tokens = analyzer_outcome.usage_output_tokens
        total_tokens = analyzer_outcome.usage_total_tokens

        if analyzer_outcome.status != "success":
            usage_obj = Usage(
                prompt_tokens=total_prompt_tokens,
                output_tokens=total_output_tokens,
                total_tokens=total_tokens,
            )
            limitations.append(
                f"Audit incomplete: {analyzer_outcome.failure_reason or 'Analyzer failed to produce result'}"
            )
            return (
                [],
                [],
                [],
                deterministic_checks,
                Decision.REVIEW,
                f"Audit failed: {analyzer_outcome.failure_reason or 'unknown reason'}",
                False,
                usage_obj,
                limitations,
            )

        # The Analyzer already rejected findings with no/hallucinated evidence for critical
        # severity (ТЗ §10 mandatory rule) — convert those into Finding objects so they show
        # up in report.rejected_findings alongside anything the Verifier rejects below.
        # Under the "no_evidence_enforcement" ablation, findings rejected ONLY for that
        # reason are let back into the candidate pool instead (hallucinated-evidence-id
        # rejections are a distinct integrity issue and stay enforced regardless).
        rejected_findings: list[Finding] = []
        reclaimed_findings: list[Finding] = []
        for entry in analyzer_outcome.rejected_findings:
            raw = entry.get("finding")
            reason = entry.get("reason", "rejected_by_analyzer")
            if not isinstance(raw, dict):
                limitations.append(f"Analyzer produced a malformed finding: {reason}")
                continue
            try:
                if ablation == "no_evidence_enforcement" and reason == "no_evidence_for_critical":
                    reclaimed_findings.append(
                        Finding.model_validate({**raw, "verification_status": VerificationStatus.pending})
                    )
                    continue
                rejected = Finding.model_validate(
                    {**raw, "verification_status": VerificationStatus.rejected}
                )
            except Exception:
                limitations.append(f"Analyzer produced a malformed finding: {reason}")
                continue
            rejected_findings.append(rejected)

        if reclaimed_findings:
            limitations.append(
                f"Ablation 'no_evidence_enforcement': {len(reclaimed_findings)} finding(s) with no "
                "evidence for a critical claim were kept instead of rejected."
            )

        candidate_findings = list(analyzer_outcome.findings) + reclaimed_findings

        surviving_findings: list[Finding] = []
        verifications: list[VerificationResult] = []

        if ablation == "no_verifier":
            limitations.append(
                "Ablation 'no_verifier': every critical/high finding was trusted as confirmed "
                "without running the Verifier."
            )
            for finding in candidate_findings:
                if finding.requires_verification:
                    surviving_findings.append(
                        finding.model_copy(update={"verification_status": VerificationStatus.confirmed})
                    )
                else:
                    surviving_findings.append(finding)
        else:
            verifier = VerifierAgent(
                llm=llm,
                source=source,
                dispatcher=dispatcher,
                evidence_store=store,
                logger=logger,
                deterministic_checks=deterministic_checks,
                deadline_s=deadline_s,
            )

            for finding in candidate_findings:
                if not finding.requires_verification:
                    surviving_findings.append(finding)
                    continue

                remaining_s = deadline_s - (time.time() - start_wall_time)
                if remaining_s <= 0:
                    verification = VerificationResult(
                        finding_id=finding.id,
                        status=VerifierStatus.uncertain,
                        confidence=0.0,
                        supporting_evidence=[],
                        contradicting_evidence=[],
                        reason_summary="verifier_failed: audit deadline exceeded before verification",
                        verifier_error="audit deadline exceeded before verification",
                    )
                else:
                    verifier.deadline_s = remaining_s
                    verification = verifier.verify(finding, audit_run_id=audit_run_id)
                    total_prompt_tokens += verifier.last_usage.prompt_tokens
                    total_output_tokens += verifier.last_usage.output_tokens
                    total_tokens += verifier.last_usage.total_tokens

                verifications.append(verification)

                if verification.status == VerifierStatus.confirmed:
                    surviving_findings.append(
                        finding.model_copy(update={"verification_status": VerificationStatus.confirmed})
                    )
                elif verification.status == VerifierStatus.rejected:
                    rejected_findings.append(
                        finding.model_copy(update={"verification_status": VerificationStatus.rejected})
                    )
                else:  # uncertain
                    surviving_findings.append(
                        finding.model_copy(update={"verification_status": VerificationStatus.needs_human_review})
                    )

        decision = decide(surviving_findings)

        n_confirmed_critical = sum(
            1
            for f in surviving_findings
            if f.severity == Severity.critical and f.verification_status == VerificationStatus.confirmed
        )
        n_confirmed_high = sum(
            1
            for f in surviving_findings
            if f.severity == Severity.high and f.verification_status == VerificationStatus.confirmed
        )
        n_uncertain = sum(
            1 for f in surviving_findings if f.verification_status == VerificationStatus.needs_human_review
        )
        executive_summary = (
            f"Analyzed {len(candidate_findings)} candidate finding(s) across "
            f"{len(deterministic_checks)} deterministic check(s). Decision: {decision.value}. "
            f"{n_confirmed_critical} confirmed critical, {n_confirmed_high} confirmed high, "
            f"{n_uncertain} finding(s) require human review, {len(rejected_findings)} rejected."
        )

        usage_obj = Usage(
            prompt_tokens=total_prompt_tokens,
            output_tokens=total_output_tokens,
            total_tokens=total_tokens,
        )

        return (
            surviving_findings,
            rejected_findings,
            verifications,
            deterministic_checks,
            decision,
            executive_summary,
            True,
            usage_obj,
            limitations,
        )
