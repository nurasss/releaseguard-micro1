# path: app/security/redaction.py
from __future__ import annotations

import re
from typing import Any


SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub Personal Access Token (classic & fine-grained)
    (re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"), "GitHub PAT (classic)"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub PAT (fine-grained)"),
    # Google API Key (AIza...)
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "Google API Key"),
    # OpenAI API Key (sk-...)
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{20,}\b"), "OpenAI API Key"),
    # AWS Access Key ID (AKIA...)
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key"),
    # Private Keys
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "Private Key Header"),
    # Slack Tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-)
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z]{10,}\b"), "Slack Token"),
]


def find_secrets(text: str) -> list[tuple[int, str, str]]:
    """Scan text line by line and return findings as (line_number, pattern_name, masked_secret).

    Masked secret reveals only the first 4 characters and the length to protect logs.
    """
    findings: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for pattern, name in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                secret = match.group(0)
                masked = f"{secret[:4]}... (len={len(secret)})"
                findings.append((idx, name, masked))
    return findings


def redact(text: str) -> str:
    """Replace all detected secret occurrences with [REDACTED:<pattern_name>]."""
    if not text or not isinstance(text, str):
        return text

    redacted_text = text
    for pattern, name in SECRET_PATTERNS:
        redacted_text = pattern.sub(f"[REDACTED:{name}]", redacted_text)
    return redacted_text


def redact_obj(obj: Any) -> Any:
    """Recursively redact string values in dicts and lists. Keys remain untouched."""
    if isinstance(obj, str):
        return redact(obj)
    elif isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [redact_obj(elem) for elem in obj]
    elif isinstance(obj, tuple):
        return tuple(redact_obj(elem) for elem in obj)
    elif isinstance(obj, set):
        return {redact_obj(elem) for elem in obj}
    return obj
