# path: app/trajectory/logger.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.audit import AgentStep
from app.security.redaction import redact_obj


def _truncate_strings(obj: Any, max_len: int = 500) -> Any:
    """Recursively truncate string values in dicts/lists to max_len characters."""
    if isinstance(obj, str):
        if len(obj) > max_len:
            return obj[:max_len] + "... [TRUNCATED]"
        return obj
    elif isinstance(obj, dict):
        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_truncate_strings(elem, max_len) for elem in obj]
    elif isinstance(obj, tuple):
        return tuple(_truncate_strings(elem, max_len) for elem in obj)
    return obj


class TrajectoryLogger:
    """Logs agent execution trajectory to append-only JSONL files and in-memory history."""

    def __init__(self, audit_run_id: str, trajectories_dir: Path | str) -> None:
        self.audit_run_id = audit_run_id
        self.trajectories_dir = Path(trajectories_dir).resolve()
        self.trajectories_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.trajectories_dir / f"{self.audit_run_id}.jsonl"
        self._steps: list[AgentStep] = []
        self._sequence: int = 0

    def log(
        self,
        component: str,
        state: str,
        tool: str | None = None,
        input_data: dict[str, Any] | None = None,
        output_summary: str = "",
        evidence_created: list[str] | None = None,
        duration_ms: int = 0,
        status: str = "success",
        retry: int = 0,
    ) -> AgentStep:
        self._sequence += 1
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Redact and truncate input_data
        clean_input = redact_obj(input_data or {})
        truncated_input = _truncate_strings(clean_input, max_len=500)
        if not isinstance(truncated_input, dict):
            truncated_input = {"value": truncated_input}

        # 2. Redact and truncate output_summary
        clean_summary = redact_obj(output_summary or "")
        if isinstance(clean_summary, str) and len(clean_summary) > 500:
            clean_summary = clean_summary[:500]

        step = AgentStep(
            audit_run_id=self.audit_run_id,
            sequence=self._sequence,
            component=component,
            state=state,
            tool=tool,
            input_redacted=truncated_input,
            output_summary=clean_summary,
            evidence_created=evidence_created or [],
            duration_ms=duration_ms,
            status=status,
            retry=retry,
            timestamp=now_utc,
        )

        # Append immediately to .jsonl
        line = json.dumps(step.model_dump(), ensure_ascii=False)
        with self.file_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        self._steps.append(step)
        return step

    def steps(self) -> list[AgentStep]:
        """Return all logged execution steps."""
        return list(self._steps)
