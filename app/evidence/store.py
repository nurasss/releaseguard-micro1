# path: app/evidence/store.py
from __future__ import annotations

import json
from typing import Any

from app.schemas.enums import SourceType
from app.schemas.evidence import Evidence, content_hash_of


class EvidenceStore:
    """In-memory evidence accumulator for an active audit run."""

    def __init__(self, audit_run_id: str, commit_sha: str) -> None:
        self.audit_run_id = audit_run_id
        self.commit_sha = commit_sha
        self._items: list[Evidence] = []
        self._counter: int = 0

    def add(
        self,
        source_type: SourceType | str,
        source_path: str,
        summary: str,
        payload: dict[str, Any],
        line_start: int | None = None,
        line_end: int | None = None,
        content: str | bytes | None = None,
    ) -> Evidence:
        self._counter += 1
        evidence_id = f"E-{self._counter:03d}"

        if content is not None:
            c_hash = content_hash_of(content)
        else:
            c_hash = content_hash_of(json.dumps(payload, sort_keys=True))

        typed_source_type = (
            source_type if isinstance(source_type, SourceType) else SourceType(source_type)
        )

        item = Evidence(
            id=evidence_id,
            audit_run_id=self.audit_run_id,
            source_ref=self.commit_sha,
            source_type=typed_source_type,
            source_path=source_path,
            summary=summary,
            content_hash=c_hash,
            line_start=line_start,
            line_end=line_end,
            payload=payload,
        )
        self._items.append(item)
        return item

    def get(self, evidence_id: str) -> Evidence | None:
        for item in self._items:
            if item.id == evidence_id:
                return item
        return None

    def all(self) -> list[Evidence]:
        return list(self._items)
