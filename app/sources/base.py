# path: app/sources/base.py
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


# Tool noise protection limits (Section 16 of TZ)
MAX_READ_FILE_LINES: int = 400
MAX_READ_FILE_CHARS: int = 40000
MAX_TREE_ENTRIES: int = 500
MAX_SEARCH_HITS: int = 50
MAX_SEARCH_LINE_CHARS: int = 300
MAX_TEST_ERROR_MESSAGE_CHARS: int = 300
MAX_GITHUB_SEARCH_FILES: int = 40


class ResolvedRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_ref: str
    commit_sha: str
    ref_type: Literal["branch", "tag", "release", "commit"]


class TreeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int


class FileSlice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    start_line: int | None = None
    end_line: int | None = None
    total_lines: int
    content: str
    truncated: bool = False
    content_hash: str


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    line_number: int
    line: str


class RepositorySource(Protocol):
    def resolve_ref(self, ref: str) -> ResolvedRef: ...

    def get_repository_metadata(self) -> dict: ...

    def get_tree(self) -> list[TreeEntry]: ...

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> FileSlice: ...

    def search_files(
        self,
        pattern: str,
        glob: str | None = None,
    ) -> list[SearchHit]: ...

    def get_workflow_files(self) -> list[str]: ...

    def get_workflow_runs(self) -> list[dict]: ...

    def get_test_report(self) -> dict | None: ...

    def get_build_report(self) -> dict | None: ...
