# path: app/orchestration/runner.py
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.baseline import BaselineAgent
from app.config import Settings, get_settings
from app.evidence.store import EvidenceStore
from app.llm.gemini import GeminiClient
from app.llm.pricing import estimate_cost_usd
from app.llm.types import LLMClient, Usage
from app.schemas.audit import AuditRun
from app.schemas.enums import (
    Decision,
    FindingCategory,
    RunStatus,
    Severity,
    VerificationStatus,
)
from app.schemas.findings import Finding
from app.schemas.integrity import IntegrityViolation, validate_report_integrity
from app.schemas.report import AuditReport
from app.sources.base import RepositorySource, ResolvedRef
from app.sources.errors import SourceError, UnknownRefError
from app.sources.fixture import LocalFixtureSource
from app.sources.github import GitHubSource
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

    def _get_llm(self) -> LLMClient:
        if self.llm_factory is not None:
            return self.llm_factory()
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
        )

    def run_repository(
        self,
        repository_url: str,
        ref: str,
        mode: Literal["baseline", "final"] = "baseline",
        timestamp: str | None = None,
        max_turns: int | None = None,
    ) -> RunOutcome:
        source = GitHubSource(
            repo_url=repository_url,
            token=self.settings.github_token,
        )
        return self._execute_audit(
            source=source,
            repository_url=repository_url,
            ref=ref,
            mode=mode,
            timestamp=timestamp,
            max_turns=max_turns,
        )

    def _execute_audit(
        self,
        source: RepositorySource,
        repository_url: str,
        ref: str,
        mode: Literal["baseline", "final"],
        timestamp: str | None,
        max_turns: int | None = None,
    ) -> RunOutcome:
        start_wall_time = time.time()
        start_ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if mode == "final":
            raise NotImplementedError("Final mode will be implemented in subsequent task")

        audit_run_id = _generate_audit_run_id(
            repository_url=repository_url,
            ref=ref,
            mode=mode,
            timestamp=start_ts,
        )

        run_artifacts_dir = (self.settings.data_dir / audit_run_id).resolve()
        run_artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve Ref
        commit_sha = ""
        try:
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
        dispatcher = ToolDispatcher(source=source, evidence=store)
        logger = TrajectoryLogger(audit_run_id=audit_run_id, trajectories_dir=self.settings.trajectories_dir)

        # 3. Execute BaselineAgent
        llm = self._get_llm()
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

        # 4. Construct findings and decision
        findings: list[Finding] = []
        limitations: list[str] = []

        if outcome.status == "success" and outcome.findings_payload:
            decision = Decision(outcome.findings_payload.get("decision", "REVIEW"))
            executive_summary = outcome.findings_payload.get("executive_summary", "")
            raw_findings = outcome.findings_payload.get("findings", [])

            for idx, rf in enumerate(raw_findings, start=1):
                f_id = f"F-{idx:03d}"
                findings.append(
                    Finding(
                        id=f_id,
                        audit_run_id=audit_run_id,
                        category=FindingCategory(rf["category"]),
                        title=rf["title"],
                        severity=Severity(rf["severity"]),
                        claim=rf["claim"],
                        confidence=float(rf["confidence"]),
                        evidence_ids=rf.get("evidence_ids", []),
                        recommended_action=rf.get("recommended_action", ""),
                        verification_status=VerificationStatus.pending,
                        origin="baseline",
                    )
                )
        else:
            decision = Decision.REVIEW
            executive_summary = f"Audit failed: {outcome.failure_reason or 'unknown reason'}"
            limitations.append(f"Audit incomplete: {outcome.failure_reason or 'Agent failed to produce result'}")

        runtime_ms = int((time.time() - start_wall_time) * 1000)
        finish_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 5. Estimate cost with full token breakdown
        usage_obj = Usage(
            prompt_tokens=outcome.usage_prompt_tokens,
            output_tokens=outcome.usage_output_tokens,
            total_tokens=outcome.usage_total_tokens,
        )
        cost_est = estimate_cost_usd(self.settings.model_id, usage_obj)
        if cost_est is None:
            cost_usd = 0.0
            limitations.append(
                f"Model {self.settings.model_id} pricing is not configured; "
                f"cost is tracked via tokens ({outcome.usage_total_tokens} total tokens)"
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
            verifications=[],
            evidence=store.all(),
            deterministic_checks=[],
            limitations=limitations,
            runtime_ms=runtime_ms,
            model_id=self.settings.model_id,
            prompt_version=self.settings.prompt_version,
            estimated_cost_usd=cost_usd,
        )

        # 7. Run integrity check (do NOT raise on violations)
        violations = validate_report_integrity(report)

        # 8. Assemble AuditRun
        run_status = RunStatus.completed if outcome.status == "success" else RunStatus.failed
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
            model_id=self.settings.model_id,
            prompt_version=self.settings.prompt_version,
            system_version=self.settings.system_version,
            mode=mode,
        )

        # 9. Save to SQLite database
        db_conn = connect(self.settings.db_path)
        init_db(db_conn)
        repo = AuditRepository(db_conn)
        repo.save_run(audit_run)
        repo.save_evidence(report.evidence)
        repo.save_findings(report.findings)
        for step in logger.steps():
            repo.save_agent_step(step)
        db_conn.close()

        # 10. Save artifacts to runs/<audit_run_id>/
        (run_artifacts_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (run_artifacts_dir / "run.json").write_text(audit_run.model_dump_json(indent=2), encoding="utf-8")

        return RunOutcome(
            run=audit_run,
            report=report,
            artifacts_dir=run_artifacts_dir,
            integrity_violations=violations,
        )
