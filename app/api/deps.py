# path: app/api/deps.py
"""FastAPI dependency wiring, mirroring the construction pattern used in app/cli.py."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends

from app.config import Settings
from app.config import get_settings as _get_settings
from app.orchestration.runner import AuditRunner
from app.storage.db import connect, init_db
from app.storage.repository import AuditRepository


def get_settings() -> Settings:
    """FastAPI-overridable indirection around app.config.get_settings()."""
    return _get_settings()


def get_runner(settings: Settings = Depends(get_settings)) -> AuditRunner:
    return AuditRunner(settings=settings)


def get_repository(settings: Settings = Depends(get_settings)) -> Iterator[AuditRepository]:
    conn = connect(settings.db_path)
    init_db(conn)
    try:
        yield AuditRepository(conn)
    finally:
        conn.close()
