from __future__ import annotations

import json
import sqlite3

from app.schemas.audit import AgentStep, AuditRun
from app.schemas.enums import (
    Decision,
    FindingCategory,
    RunStatus,
    Severity,
    SourceType,
    VerificationStatus,
    VerifierStatus,
)
from app.schemas.evidence import Evidence
from app.schemas.findings import Finding
from app.schemas.verification import VerificationResult


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_run(self, run: AuditRun) -> None:
        """Save AuditRun to database using INSERT OR REPLACE."""
        status_val = run.status.value if isinstance(run.status, RunStatus) else run.status
        final_decision_val = (
            run.final_decision.value
            if isinstance(run.final_decision, Decision)
            else run.final_decision
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO audit_runs (
                id, repository_url, requested_ref, commit_sha, status, final_decision,
                started_at, finished_at, runtime_ms, estimated_cost, model_id,
                prompt_version, system_version, mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                run.id,
                run.repository_url,
                run.requested_ref,
                run.commit_sha,
                status_val,
                final_decision_val,
                run.started_at,
                run.finished_at,
                run.runtime_ms,
                run.estimated_cost_usd,
                run.model_id,
                run.prompt_version,
                run.system_version,
                run.mode,
            ),
        )
        self.conn.commit()

    def update_run(self, run: AuditRun) -> None:
        """Update AuditRun in database."""
        self.save_run(run)

    def get_run(self, run_id: str) -> AuditRun | None:
        """Retrieve AuditRun by ID or return None if not found."""
        cursor = self.conn.execute(
            "SELECT * FROM audit_runs WHERE id = ?;",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        final_decision = (
            Decision(row["final_decision"]) if row["final_decision"] is not None else None
        )
        return AuditRun(
            id=row["id"],
            repository_url=row["repository_url"],
            requested_ref=row["requested_ref"],
            commit_sha=row["commit_sha"],
            status=RunStatus(row["status"]),
            final_decision=final_decision,
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            runtime_ms=row["runtime_ms"],
            estimated_cost_usd=float(row["estimated_cost"])
            if row["estimated_cost"] is not None
            else 0.0,
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
            system_version=row["system_version"],
            mode=row["mode"],
        )

    def save_evidence(self, evidence_list: list[Evidence]) -> None:
        """Save a list of Evidence objects idempotently."""
        for ev in evidence_list:
            source_type_val = (
                ev.source_type.value
                if isinstance(ev.source_type, SourceType)
                else ev.source_type
            )
            payload_str = json.dumps(ev.payload)
            self.conn.execute(
                """
                INSERT OR REPLACE INTO evidence (
                    id, audit_run_id, source_type, source_path, source_ref,
                    line_start, line_end, content_hash, summary, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ev.id,
                    ev.audit_run_id,
                    source_type_val,
                    ev.source_path,
                    ev.source_ref,
                    ev.line_start,
                    ev.line_end,
                    ev.content_hash,
                    ev.summary,
                    payload_str,
                ),
            )
        self.conn.commit()

    def get_evidence(self, run_id: str) -> list[Evidence]:
        """Retrieve all Evidence for a given audit_run_id sorted numerically by ID."""
        cursor = self.conn.execute(
            """
            SELECT * FROM evidence
            WHERE audit_run_id = ?
            ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) ASC, id ASC;
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        result: list[Evidence] = []
        for row in rows:
            payload = json.loads(row["payload"]) if row["payload"] else {}
            result.append(
                Evidence(
                    id=row["id"],
                    audit_run_id=row["audit_run_id"],
                    source_type=SourceType(row["source_type"]),
                    source_path=row["source_path"],
                    source_ref=row["source_ref"],
                    line_start=row["line_start"],
                    line_end=row["line_end"],
                    content_hash=row["content_hash"],
                    summary=row["summary"],
                    payload=payload,
                )
            )
        return result

    def save_findings(self, findings: list[Finding]) -> None:
        """Save findings and populate finding_evidence relational table."""
        for finding in findings:
            category_val = (
                finding.category.value
                if isinstance(finding.category, FindingCategory)
                else finding.category
            )
            severity_val = (
                finding.severity.value
                if isinstance(finding.severity, Severity)
                else finding.severity
            )
            verification_status_val = (
                finding.verification_status.value
                if isinstance(finding.verification_status, VerificationStatus)
                else finding.verification_status
            )
            self.conn.execute(
                """
                INSERT OR REPLACE INTO findings (
                    id, audit_run_id, category, title, severity, claim,
                    confidence, verification_status, recommended_action, origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    finding.id,
                    finding.audit_run_id,
                    category_val,
                    finding.title,
                    severity_val,
                    finding.claim,
                    finding.confidence,
                    verification_status_val,
                    finding.recommended_action,
                    finding.origin,
                ),
            )
            self.conn.execute(
                "DELETE FROM finding_evidence WHERE finding_id = ? AND audit_run_id = ?;",
                (finding.id, finding.audit_run_id),
            )
            for ev_id in finding.evidence_ids:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO finding_evidence (
                        finding_id, evidence_id, audit_run_id
                    ) VALUES (?, ?, ?);
                    """,
                    (finding.id, ev_id, finding.audit_run_id),
                )
        self.conn.commit()

    def get_findings(self, run_id: str) -> list[Finding]:
        """Retrieve findings with evidence_ids restored, sorted numerically by ID."""
        cursor = self.conn.execute(
            """
            SELECT * FROM findings
            WHERE audit_run_id = ?
            ORDER BY CAST(SUBSTR(id, 3) AS INTEGER) ASC, id ASC;
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        result: list[Finding] = []
        for row in rows:
            ev_cursor = self.conn.execute(
                """
                SELECT evidence_id FROM finding_evidence
                WHERE finding_id = ? AND audit_run_id = ?
                ORDER BY rowid ASC;
                """,
                (row["id"], run_id),
            )
            evidence_ids = [ev_row["evidence_id"] for ev_row in ev_cursor.fetchall()]
            result.append(
                Finding(
                    id=row["id"],
                    audit_run_id=row["audit_run_id"],
                    category=FindingCategory(row["category"]),
                    title=row["title"],
                    severity=Severity(row["severity"]),
                    claim=row["claim"],
                    confidence=row["confidence"],
                    evidence_ids=evidence_ids,
                    recommended_action=row["recommended_action"],
                    verification_status=VerificationStatus(row["verification_status"]),
                    origin=row["origin"],
                )
            )
        return result

    def save_verification(
        self, verification: VerificationResult, audit_run_id: str
    ) -> None:
        """Save VerificationResult for a given audit_run_id using INSERT OR REPLACE."""
        status_val = (
            verification.status.value
            if isinstance(verification.status, VerifierStatus)
            else verification.status
        )
        supporting_json = json.dumps(verification.supporting_evidence)
        contradicting_json = json.dumps(verification.contradicting_evidence)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO verification_results (
                finding_id, audit_run_id, status, confidence, reason_summary,
                supporting_evidence, contradicting_evidence, verifier_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                verification.finding_id,
                audit_run_id,
                status_val,
                verification.confidence,
                verification.reason_summary,
                supporting_json,
                contradicting_json,
                verification.verifier_error,
            ),
        )
        self.conn.commit()

    def get_verifications(self, run_id: str) -> list[VerificationResult]:
        """Retrieve all VerificationResults for a given audit_run_id."""
        cursor = self.conn.execute(
            "SELECT * FROM verification_results WHERE audit_run_id = ? ORDER BY id ASC;",
            (run_id,),
        )
        rows = cursor.fetchall()
        result: list[VerificationResult] = []
        for row in rows:
            supporting_evidence = (
                json.loads(row["supporting_evidence"])
                if row["supporting_evidence"]
                else []
            )
            contradicting_evidence = (
                json.loads(row["contradicting_evidence"])
                if row["contradicting_evidence"]
                else []
            )
            result.append(
                VerificationResult(
                    finding_id=row["finding_id"],
                    status=VerifierStatus(row["status"]),
                    confidence=row["confidence"],
                    supporting_evidence=supporting_evidence,
                    contradicting_evidence=contradicting_evidence,
                    reason_summary=row["reason_summary"],
                    verifier_error=row["verifier_error"],
                )
            )
        return result

    def save_agent_step(self, step: AgentStep) -> None:
        """Save an AgentStep execution trace using INSERT OR REPLACE."""
        input_redacted_str = json.dumps(step.input_redacted)
        evidence_created_str = json.dumps(step.evidence_created)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO agent_steps (
                audit_run_id, agent_name, sequence, state, tool_name,
                input_redacted, output_summary, evidence_created, status,
                duration_ms, retry, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                step.audit_run_id,
                step.component,
                step.sequence,
                step.state,
                step.tool,
                input_redacted_str,
                step.output_summary,
                evidence_created_str,
                step.status,
                step.duration_ms,
                step.retry,
                step.timestamp,
            ),
        )
        self.conn.commit()

    def get_agent_steps(self, run_id: str) -> list[AgentStep]:
        """Retrieve all AgentSteps for a run sorted by sequence."""
        cursor = self.conn.execute(
            "SELECT * FROM agent_steps WHERE audit_run_id = ? ORDER BY sequence ASC;",
            (run_id,),
        )
        rows = cursor.fetchall()
        result: list[AgentStep] = []
        for row in rows:
            input_redacted = (
                json.loads(row["input_redacted"]) if row["input_redacted"] else {}
            )
            evidence_created = (
                json.loads(row["evidence_created"]) if row["evidence_created"] else []
            )
            result.append(
                AgentStep(
                    audit_run_id=row["audit_run_id"],
                    sequence=row["sequence"],
                    component=row["agent_name"],
                    state=row["state"],
                    tool=row["tool_name"],
                    input_redacted=input_redacted,
                    output_summary=row["output_summary"] or "",
                    evidence_created=evidence_created,
                    duration_ms=row["duration_ms"],
                    status=row["status"],
                    retry=row["retry"],
                    timestamp=row["timestamp"],
                )
            )
        return result

    def save_evaluation_result(
        self,
        case_id: str,
        run_id: str,
        mode: str,
        recall: float,
        precision: float,
        f1: float,
        evidence_coverage: float,
        decision_correct: bool | int,
        runtime_ms: int,
        estimated_cost: float,
    ) -> None:
        """Save evaluation benchmark result."""
        decision_correct_int = 1 if decision_correct else 0
        self.conn.execute(
            """
            INSERT INTO evaluation_results (
                case_id, run_id, mode, recall, precision, f1,
                evidence_coverage, decision_correct, runtime_ms, estimated_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                case_id,
                run_id,
                mode,
                recall,
                precision,
                f1,
                evidence_coverage,
                decision_correct_int,
                runtime_ms,
                estimated_cost,
            ),
        )
        self.conn.commit()
