"""Pure helpers that do not touch environment variables."""

from __future__ import annotations


def format_subject(event_name: str, account_id: str) -> str:
    return f"[{account_id}] {event_name}"
