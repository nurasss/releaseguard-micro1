# path: app/llm/errors.py
from __future__ import annotations


class LLMError(Exception):
    """Base exception for all LLM client errors."""


class LLMTimeout(LLMError):
    """Raised when an LLM request times out."""


class LLMRateLimited(LLMError):
    """Raised when an LLM request is rate-limited (429)."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMInvalidResponse(LLMError):
    """Raised when LLM returns an empty, unparseable, or invalid response."""


class LLMAuthError(LLMError):
    """Raised when authentication fails (401/403)."""


class LLMServerError(LLMError):
    """Raised when the LLM provider returns a 5xx server error."""
