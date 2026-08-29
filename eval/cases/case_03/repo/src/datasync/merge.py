"""Record merge utilities."""

from __future__ import annotations


def merge_records(source: dict, target: dict) -> dict:
    merged = dict(target)
    merged.update(source)
    return merged


def diff_keys(source: dict, target: dict) -> set:
    return set(source) - set(target)
