"""Core utilities for the toolbox CLI."""

from __future__ import annotations

import os


def add_numbers(a: float, b: float) -> float:
    return a + b


def slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def load_config() -> dict:
    return {
        "api_key": os.environ.get("TOOLBOX_API_KEY", ""),
        "log_level": os.environ.get("TOOLBOX_LOG_LEVEL", "INFO"),
        "timeout_seconds": int(os.environ.get("TOOLBOX_TIMEOUT_SECONDS", "30")),
    }
