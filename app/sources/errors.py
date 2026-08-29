# path: app/sources/errors.py
from __future__ import annotations


class SourceError(Exception):
    """Base exception for all repository source operations."""


class UnknownRefError(SourceError):
    """Raised when the requested ref cannot be found or resolved."""


class PathEscapeError(SourceError):
    """Raised when an access path escapes the allowed repository directory."""


class FileNotFoundInRepoError(SourceError):
    """Raised when a requested file is not found within the repository."""


class InvalidPathError(SourceError):
    """Raised when an invalid file path format is provided."""


class GitHubAPIError(SourceError):
    """Raised when the GitHub API returns an error or unexpected status."""
