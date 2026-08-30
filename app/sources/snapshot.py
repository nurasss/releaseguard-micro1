"""Immutable repository snapshot metadata for reproducible audit runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.sources.base import RepositorySource, ResolvedRef, TreeEntry


class SnapshotManifest(BaseModel):
    """The identity of the repository state used by an audit.

    The manifest intentionally contains no file contents.  The immutable commit
    SHA is the source-of-truth identity; the bounded tree digest is a useful
    diagnostic that detects a changed fixture or an incomplete source adapter.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    repository_url: str
    requested_ref: str
    resolved_ref_type: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(ge=0)
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at_utc: str


def tree_digest(tree: list[TreeEntry]) -> str:
    """Hash the sorted path/size manifest without persisting repository data."""
    lines = [f"{entry.path}:{entry.size_bytes}" for entry in sorted(tree, key=lambda item: item.path)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


class SnapshotManager:
    """Capture and persist a small, content-free snapshot manifest."""

    def capture(
        self,
        source: RepositorySource,
        repository_url: str,
        requested_ref: str,
        resolved_ref: ResolvedRef,
        output_path: Path | str,
    ) -> SnapshotManifest:
        tree = source.get_tree()
        manifest = SnapshotManifest(
            repository_url=repository_url,
            requested_ref=requested_ref,
            resolved_ref_type=resolved_ref.ref_type,
            commit_sha=resolved_ref.commit_sha,
            file_count=len(tree),
            tree_sha256=tree_digest(tree),
            captured_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return manifest


__all__ = ["SnapshotManager", "SnapshotManifest", "tree_digest"]
