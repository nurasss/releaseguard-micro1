# path: app/tools/dispatch.py
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.evidence.store import EvidenceStore
from app.llm.types import ToolCall
from app.schemas.enums import SourceType
from app.security.redaction import redact_file_content, redact_obj
from app.sources.base import RepositorySource
from app.sources.errors import (
    FileNotFoundInRepoError,
    InvalidPathError,
    PathEscapeError,
    SourceError,
    UnknownRefError,
)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool
    result: dict = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0


class ToolDispatcher:
    """Dispatches tool calls against repository sources and records evidence."""

    def __init__(
        self,
        source: RepositorySource,
        evidence: EvidenceStore,
        normalize_outputs: bool = True,
    ) -> None:
        self.source = source
        self.evidence = evidence
        self.normalize_outputs = normalize_outputs

    def _record(
        self,
        *,
        source_type: SourceType,
        source_path: str,
        summary: str,
        payload: dict[str, Any],
        line_start: int | None = None,
        line_end: int | None = None,
        content: str | bytes | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        """Persist and return the same redacted payload to the model caller."""
        ev = self.evidence.add(
            source_type=source_type,
            source_path=source_path,
            summary=summary,
            payload=payload,
            line_start=line_start,
            line_end=line_end,
            content=content,
        )
        safe_payload = redact_obj(dict(ev.payload))
        if self.normalize_outputs:
            result = safe_payload
        else:
            # Keep the ablation bounded and persistence-safe while removing the
            # normalized object shape that the normal path gives to the agent.
            # This is intentionally a serialized raw tool payload, not an
            # unbounded repository read and never includes secret-file bodies.
            result = {"raw_output": str(safe_payload)}
        result["evidence_ids"] = [ev.id]
        return ev, result

    def execute(self, call: ToolCall) -> ToolResult:
        start_time = time.perf_counter()
        tool_name = call.name
        args = call.args or {}

        try:
            if tool_name == "get_repository_metadata":
                metadata = dict(self.source.get_repository_metadata())
                ev, metadata = self._record(
                    source_type=SourceType.repository_metadata,
                    source_path="repository_metadata.json",
                    summary="Repository metadata",
                    payload=metadata,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=metadata,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "get_tree":
                tree = self.source.get_tree()
                tree_dicts = [e.model_dump() for e in tree]
                payload = {"tree": tree_dicts, "total_files": len(tree_dicts)}
                ev, payload = self._record(
                    source_type=SourceType.git_metadata,
                    source_path=".",
                    summary="Repository file tree",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "read_file":
                if "path" not in args or not isinstance(args["path"], str):
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool=tool_name,
                        ok=False,
                        error="Missing or invalid required argument: 'path' must be a string",
                        duration_ms=duration,
                    )

                path = args["path"]
                start_line = args.get("start_line")
                end_line = args.get("end_line")

                if start_line is not None and not isinstance(start_line, int):
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool=tool_name,
                        ok=False,
                        error="Invalid argument: 'start_line' must be an integer",
                        duration_ms=duration,
                    )
                if end_line is not None and not isinstance(end_line, int):
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool=tool_name,
                        ok=False,
                        error="Invalid argument: 'end_line' must be an integer",
                        duration_ms=duration,
                    )

                slice_res = self.source.read_file(path=path, start_line=start_line, end_line=end_line)
                slice_dict = slice_res.model_dump()
                slice_dict["content"] = redact_file_content(path, slice_res.content)
                ev, slice_dict = self._record(
                    source_type=SourceType.github_file,
                    source_path=path,
                    summary=f"Read file {path} (lines {slice_res.start_line}-{slice_res.end_line})",
                    payload=slice_dict,
                    line_start=slice_res.start_line,
                    line_end=slice_res.end_line,
                    content=slice_res.content,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=slice_dict,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "search_files":
                if "pattern" not in args or not isinstance(args["pattern"], str):
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool=tool_name,
                        ok=False,
                        error="Missing or invalid required argument: 'pattern' must be a string",
                        duration_ms=duration,
                    )

                pattern = args["pattern"]
                glob = args.get("glob")
                if glob is not None and not isinstance(glob, str):
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool=tool_name,
                        ok=False,
                        error="Invalid argument: 'glob' must be a string",
                        duration_ms=duration,
                    )

                hits = self.source.search_files(pattern=pattern, glob=glob)
                hits_dicts = [h.model_dump() for h in hits]
                payload = {"pattern": pattern, "glob": glob, "hits": hits_dicts, "total_hits": len(hits_dicts)}
                ev, payload = self._record(
                    source_type=SourceType.github_file,
                    source_path=".",
                    summary=f"Search pattern {pattern!r} in repository",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "get_workflow_files":
                files = self.source.get_workflow_files()
                payload = {"workflow_files": files, "count": len(files)}
                ev, payload = self._record(
                    source_type=SourceType.github_actions,
                    source_path=".github/workflows",
                    summary="GitHub Actions workflow configurations",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "get_workflow_runs":
                runs = self.source.get_workflow_runs()
                payload = {"workflow_runs": runs, "count": len(runs)}
                ev, payload = self._record(
                    source_type=SourceType.github_actions,
                    source_path="github_actions_runs.json",
                    summary="GitHub Actions workflow runs",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "get_test_report":
                report = self.source.get_test_report()
                payload = {"test_report": report}
                ev, payload = self._record(
                    source_type=SourceType.test_result,
                    source_path="test_report.json",
                    summary="Test execution report",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            elif tool_name == "get_build_report":
                report = self.source.get_build_report()
                payload = {"build_report": report}
                ev, payload = self._record(
                    source_type=SourceType.build_result,
                    source_path="build_report.json",
                    summary="Build and packaging report",
                    payload=payload,
                )
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=True,
                    result=payload,
                    evidence_ids=[ev.id],
                    duration_ms=duration,
                )

            else:
                duration = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool=tool_name,
                    ok=False,
                    error=f"Unknown tool: {tool_name}",
                    duration_ms=duration,
                )

        except (PathEscapeError, UnknownRefError, FileNotFoundInRepoError, InvalidPathError, SourceError) as exc:
            duration = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool=tool_name,
                ok=False,
                error=str(exc),
                duration_ms=duration,
            )
        except Exception as exc:
            duration = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool=tool_name,
                ok=False,
                error=f"Unexpected error executing {tool_name}: {exc}",
                duration_ms=duration,
            )
