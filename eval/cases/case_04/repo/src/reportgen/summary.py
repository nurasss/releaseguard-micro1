"""CSV summary helpers."""

from __future__ import annotations

import csv
from io import StringIO


def parse_rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(StringIO(csv_text)))


def total_column(rows: list[dict], column: str) -> float:
    return sum(float(row[column]) for row in rows)
