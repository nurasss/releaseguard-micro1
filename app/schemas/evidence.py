from __future__ import annotations

import hashlib
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import SourceType


def content_hash_of(data: str | bytes) -> str:
    """Return SHA-256 hash formatted as 'sha256:<hex>'."""
    if isinstance(data, str):
        payload_bytes = data.encode("utf-8")
    else:
        payload_bytes = data
    digest = hashlib.sha256(payload_bytes).hexdigest()
    return f"sha256:{digest}"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^E-\d{3,}$")
    audit_run_id: str
    source_type: SourceType
    source_path: str
    source_ref: str = Field(pattern=r"^[0-9a-f]{40}$")
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_line_range(self) -> Evidence:
        if self.line_end is not None:
            if self.line_start is None:
                raise ValueError("line_start must be provided when line_end is specified")
            if self.line_end < self.line_start:
                raise ValueError(
                    f"line_end ({self.line_end}) must be >= line_start ({self.line_start})"
                )
        return self
