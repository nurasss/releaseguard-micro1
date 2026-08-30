# path: app/security/redaction.py
from __future__ import annotations

import re
from pathlib import PurePosixPath
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

# A filename is itself a security signal. Secret files often contain values
# that do not use a recognisable provider prefix (for example ``PASSWORD=x``),
# so pattern matching alone is not sufficient before an evidence payload is
# persisted or sent to a model.
SAFE_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secret.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".kdbx",
}
SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[-_.])(secret|secrets|credential|credentials|password|passwd|token|private[-_.]?key)(?:$|[-_.])",
    re.IGNORECASE,
)


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


def is_sensitive_path(path: str) -> bool:
    """Return whether a repository path should be treated as a secret file."""
    if not isinstance(path, str) or not path:
        return False
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    if name in SAFE_TEMPLATE_NAMES:
        return False
    if name in SENSITIVE_BASENAMES or name.endswith(tuple(SENSITIVE_SUFFIXES)):
        return True
    return bool(SENSITIVE_NAME_RE.search(name))


def redact_file_content(path: str, content: str) -> str:
    """Redact file text, omitting the complete body for secret-looking files."""
    if is_sensitive_path(path):
        line_count = len(content.splitlines())
        return f"[REDACTED:secret file contents omitted; lines={line_count}]"
    return redact(content)


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


def redact_evidence_payload(source_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a persistence-safe evidence payload.

    This helper is intentionally reusable at both the in-memory EvidenceStore
    boundary and the SQLite repository boundary, so a caller cannot bypass the
    secret-file omission by constructing an Evidence object directly.
    """
    safe_payload = redact_obj(payload)
    if not is_sensitive_path(source_path):
        return safe_payload

    structural_keys = {
        "path",
        "start_line",
        "end_line",
        "total_lines",
        "truncated",
        "content_hash",
        "evidence_ids",
    }
    return {
        key: value if key in structural_keys else "[REDACTED:secret file contents omitted]"
        for key, value in safe_payload.items()
    }
