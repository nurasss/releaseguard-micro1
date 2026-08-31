# path: app/api/main.py
"""ReleaseGuard HTTP API (TZ Section 31).

Run with: uvicorn app.api.main:app

MVP simplification (TZ Section 38 priority cuts): there is no async job queue.
`POST /api/v1/audits` and `POST /api/v1/evaluations` execute the underlying
work synchronously, in-process, within the request/response cycle, and only
return once the run has finished. The response `status` field therefore
reflects the *actual* terminal status of the run, not a literal "queued"
placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

from app.api.deps import get_repository, get_runner, get_settings
from app.api.schemas import (
    AuditDetailResponse,
    CreateAuditRequest,
    CreateAuditResponse,
    CreateEvaluationRequest,
    CreateEvaluationResponse,
    FindingsResponse,
    HealthResponse,
)
from app.config import Settings
from app.orchestration.runner import AuditRunner
from app.sources.errors import PrivateRepositoryError
from app.storage.db import connect, init_db
from app.storage.repository import AuditRepository

app = FastAPI(title="ReleaseGuard API", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
def ready(settings: Settings = Depends(get_settings)) -> HealthResponse:
    try:
        conn = connect(settings.db_path)
        init_db(conn)
        conn.close()
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=503, detail=f"Database not reachable: {exc}") from exc
    return HealthResponse(status="ready")


@app.post("/api/v1/audits", response_model=CreateAuditResponse)
def create_audit(
    body: CreateAuditRequest,
    runner: AuditRunner = Depends(get_runner),
) -> CreateAuditResponse:
    try:
        outcome = runner.run_repository(
            repository_url=body.repository_url,
            ref=body.ref,
            mode=body.mode,
        )
    except PrivateRepositoryError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit run failed: {exc}") from exc

    return CreateAuditResponse(audit_id=outcome.run.id, status=outcome.run.status.value)


def _load_report_json(settings: Settings, audit_id: str) -> dict | None:
    report_path = Path(settings.data_dir) / audit_id / "report.json"
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


@app.get("/api/v1/audits/{audit_id}", response_model=AuditDetailResponse)
def get_audit(
    audit_id: str,
    repo: AuditRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> AuditDetailResponse:
    run = repo.get_run(audit_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Audit run {audit_id!r} not found")

    report = _load_report_json(settings, audit_id)
    return AuditDetailResponse(
        audit_id=audit_id,
        run=run.model_dump(mode="json"),
        report=report,
    )


@app.get("/api/v1/audits/{audit_id}/findings", response_model=FindingsResponse)
def get_audit_findings(
    audit_id: str,
    repo: AuditRepository = Depends(get_repository),
) -> FindingsResponse:
    run = repo.get_run(audit_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Audit run {audit_id!r} not found")

    findings = repo.get_findings(audit_id)
    return FindingsResponse(
        audit_id=audit_id,
        findings=[f.model_dump(mode="json") for f in findings],
    )


@app.get("/api/v1/audits/{audit_id}/trajectory")
def get_audit_trajectory(
    audit_id: str,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    trajectory_path = Path(settings.trajectories_dir) / f"{audit_id}.jsonl"
    if not trajectory_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Trajectory for audit run {audit_id!r} not found",
        )

    steps: list[dict] = []
    with trajectory_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))
    return steps


@app.get("/api/v1/audits/{audit_id}/report.md")
def get_audit_report_markdown(
    audit_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    report_md_path = Path(settings.data_dir) / audit_id / "report.md"
    if not report_md_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"report.md for audit run {audit_id!r} is not available",
        )
    return Response(
        content=report_md_path.read_text(encoding="utf-8"),
        media_type="text/markdown",
    )


@app.post("/api/v1/evaluations", response_model=CreateEvaluationResponse)
def create_evaluation(
    body: CreateEvaluationRequest,
    settings: Settings = Depends(get_settings),
) -> CreateEvaluationResponse:
    # Imported lazily so the eval package (and its heavier deps) are only
    # pulled in when this endpoint is actually exercised.
    from eval.run import run_evaluation

    try:
        results_payload, exit_code = run_evaluation(
            mode=body.mode,
            case_ids=body.cases,
            db_path=settings.db_path,
            runs_dir=str(settings.data_dir),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation run failed: {exc}") from exc

    evaluation_id = results_payload["meta"]["run_label"]
    status = "completed" if exit_code == 0 else "completed_with_failures"
    return CreateEvaluationResponse(evaluation_id=evaluation_id, status=status)


@app.get("/api/v1/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str) -> dict:
    results_file = Path("eval/results") / evaluation_id / "results.json"
    if not results_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Evaluation {evaluation_id!r} not found",
        )
    return json.loads(results_file.read_text(encoding="utf-8"))


# Keep the API and the browser client in one deployable process. API routes are
# registered above this mount, so they continue to take precedence over the
# static fallback at the root path.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
