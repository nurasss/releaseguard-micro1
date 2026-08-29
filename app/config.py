# path: app/config.py
from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RG_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),
    )

    llm_provider: Literal["google"] = "google"
    # Model frozen due to latency requirement: gemini-2.5-flash (1.3s) vs gemini-3.7-flash (23.3s) to satisfy NFR-08 (<=5min per fixture).
    model_id: str = "gemini-2.5-flash"
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "RG_API_KEY"),
    )
    github_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_TOKEN", "RG_GITHUB_TOKEN"),
    )
    min_request_interval_ms: int = 6500
    data_dir: Path = Path("./runs")
    db_path: Path = Path("./runs/releaseguard.sqlite3")
    trajectories_dir: Path = Path("./trajectories")
    artifacts_dir: Path = Path("./artifacts")
    prompt_version: str = "p1"
    system_version: str = "0.1.0"
    audit_deadline_s: int = 300
    request_timeout_s: int = 120
    max_retries: int = 4

    def __repr__(self) -> str:
        masked_api_key = "***" if self.api_key is not None else None
        masked_github_token = "***" if self.github_token is not None else None
        return (
            f"Settings(llm_provider={self.llm_provider!r}, "
            f"model_id={self.model_id!r}, "
            f"api_key={masked_api_key!r}, "
            f"github_token={masked_github_token!r}, "
            f"min_request_interval_ms={self.min_request_interval_ms!r}, "
            f"data_dir={self.data_dir!r}, "
            f"db_path={self.db_path!r}, "
            f"trajectories_dir={self.trajectories_dir!r}, "
            f"artifacts_dir={self.artifacts_dir!r}, "
            f"prompt_version={self.prompt_version!r}, "
            f"system_version={self.system_version!r}, "
            f"audit_deadline_s={self.audit_deadline_s!r}, "
            f"request_timeout_s={self.request_timeout_s!r}, "
            f"max_retries={self.max_retries!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
