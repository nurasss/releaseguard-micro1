"""Startup configuration for the notifier service."""

from __future__ import annotations

import os

# Required: the SMTP relay host. There is no default because sending mail
# without a configured relay is not a safe fallback. It is not documented
# in README.md or .env.example.
SMTP_HOST = os.environ["SMTP_HOST"]

SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
API_TIMEOUT_SECONDS = int(os.environ.get("API_TIMEOUT_SECONDS", "30"))
