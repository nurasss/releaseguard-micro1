from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Connect to SQLite database with WAL journal mode, foreign keys, and Row factory."""
    if isinstance(db_path, Path):
        db_path_str = str(db_path)
    else:
        db_path_str = db_path

    if db_path_str != ":memory:":
        Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path_str)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize SQLite database schema and migrations idempotently."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_runs (
            id TEXT PRIMARY KEY,
            repository_url TEXT NOT NULL,
            requested_ref TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            status TEXT NOT NULL,
            final_decision TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            runtime_ms INTEGER,
            estimated_cost REAL DEFAULT 0.0,
            model_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            system_version TEXT NOT NULL,
            mode TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT NOT NULL,
            audit_run_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            line_start INTEGER,
            line_end INTEGER,
            content_hash TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT,
            PRIMARY KEY (id, audit_run_id),
            FOREIGN KEY (audit_run_id) REFERENCES audit_runs (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS findings (
            id TEXT NOT NULL,
            audit_run_id TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            severity TEXT NOT NULL,
            claim TEXT NOT NULL,
            confidence REAL NOT NULL,
            verification_status TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            origin TEXT NOT NULL,
            PRIMARY KEY (id, audit_run_id),
            FOREIGN KEY (audit_run_id) REFERENCES audit_runs (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS finding_evidence (
            finding_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            audit_run_id TEXT NOT NULL,
            PRIMARY KEY (finding_id, evidence_id, audit_run_id)
        );

        CREATE TABLE IF NOT EXISTS verification_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id TEXT NOT NULL,
            audit_run_id TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason_summary TEXT NOT NULL,
            supporting_evidence TEXT,
            contradicting_evidence TEXT,
            verifier_error TEXT,
            UNIQUE(audit_run_id, finding_id)
        );

        CREATE TABLE IF NOT EXISTS agent_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_run_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            state TEXT NOT NULL,
            tool_name TEXT,
            input_redacted TEXT,
            output_summary TEXT,
            evidence_created TEXT,
            status TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            retry INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            UNIQUE(audit_run_id, sequence)
        );

        CREATE TABLE IF NOT EXISTS evaluation_cases (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            expected_decision TEXT NOT NULL,
            expected_blockers TEXT,
            metadata TEXT,
            held_out INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS evaluation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            recall REAL NOT NULL,
            precision REAL NOT NULL,
            f1 REAL NOT NULL,
            evidence_coverage REAL NOT NULL,
            decision_correct INTEGER NOT NULL,
            runtime_ms INTEGER NOT NULL,
            estimated_cost REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """
    )
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES ('1', ?);",
        (now_utc_str,),
    )
    conn.commit()
