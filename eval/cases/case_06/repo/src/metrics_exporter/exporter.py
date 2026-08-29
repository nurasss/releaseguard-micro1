"""Prometheus-format metric formatting."""

from __future__ import annotations


def format_metric(name: str, value: float) -> str:
    return f"{name} {value}"
