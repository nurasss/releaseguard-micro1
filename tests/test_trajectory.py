# path: tests/test_trajectory.py
import json
from pathlib import Path

from app.trajectory.logger import TrajectoryLogger


def test_trajectory_logger_sequence_and_jsonl_output(tmp_path: Path) -> None:
    traj_dir = tmp_path / "trajectories"
    run_id = "aud_test123456"
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=traj_dir)

    dummy_secret = "gh" + "p_" + "123456789012345678901234567890123456"
    step1 = logger.log(
        component="baseline",
        state="init",
        input_data={"param": "hello"},
        output_summary="Starting audit",
    )
    step2 = logger.log(
        component="baseline",
        state="tool_call",
        tool="get_tree",
        input_data={"secret_token": dummy_secret},
        output_summary="Tree retrieved",
        evidence_created=["E-001"],
        duration_ms=120,
    )

    assert step1.sequence == 1
    assert step2.sequence == 2
    assert step1.timestamp.endswith("Z")
    assert step2.timestamp.endswith("Z")
    assert len(logger.steps()) == 2

    # Verify JSONL file on disk
    jsonl_path = traj_dir / f"{run_id}.jsonl"
    assert jsonl_path.exists()
    lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(lines) == 2
    assert lines[0]["sequence"] == 1
    assert lines[1]["sequence"] == 2
    assert lines[1]["evidence_created"] == ["E-001"]
    assert lines[1]["duration_ms"] == 120
    # Check secret redaction
    assert dummy_secret not in jsonl_path.read_text(encoding="utf-8")
    assert "[REDACTED:GitHub PAT (classic)]" in lines[1]["input_redacted"]["secret_token"]


def test_trajectory_logger_truncation(tmp_path: Path) -> None:
    traj_dir = tmp_path / "trajectories"
    run_id = "aud_truncation"
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=traj_dir)

    huge_input = "A" * 800
    huge_summary = "B" * 800

    step = logger.log(
        component="analyzer",
        state="review",
        input_data={"content": huge_input},
        output_summary=huge_summary,
    )

    assert len(step.input_redacted["content"]) <= 520
    assert "[TRUNCATED]" in step.input_redacted["content"]
    assert len(step.output_summary) == 500


def test_trajectory_logger_retry_and_status(tmp_path: Path) -> None:
    traj_dir = tmp_path / "trajectories"
    run_id = "aud_retry_status"
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=traj_dir)

    step = logger.log(
        component="verifier",
        state="retry_execution",
        tool="search_files",
        input_data={"pattern": "test"},
        output_summary="Retry after error",
        status="error",
        retry=2,
        duration_ms=45,
    )

    assert step.status == "error"
    assert step.retry == 2
    assert step.duration_ms == 45
    assert step.tool == "search_files"


def test_trajectory_logger_non_dict_input(tmp_path: Path) -> None:
    traj_dir = tmp_path / "trajectories"
    run_id = "aud_non_dict"
    logger = TrajectoryLogger(audit_run_id=run_id, trajectories_dir=traj_dir)

    step = logger.log(
        component="baseline",
        state="test",
        input_data=None,
        output_summary="",
    )
    assert step.input_redacted == {}
