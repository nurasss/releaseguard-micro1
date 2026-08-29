from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    github_file = "github_file"
    github_actions = "github_actions"
    repository_metadata = "repository_metadata"
    manifest = "manifest"
    lockfile = "lockfile"
    test_result = "test_result"
    build_result = "build_result"
    deterministic_check = "deterministic_check"
    git_metadata = "git_metadata"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingCategory(str, Enum):
    ci = "ci"
    tests = "tests"
    build = "build"
    release_metadata = "release_metadata"
    dependencies = "dependencies"
    config = "config"
    migrations = "migrations"
    security = "security"
    docs = "docs"
    other = "other"


class VerificationStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"
    needs_human_review = "needs_human_review"


class VerifierStatus(str, Enum):
    confirmed = "confirmed"
    rejected = "rejected"
    uncertain = "uncertain"


class Decision(str, Enum):
    GO = "GO"
    REVIEW = "REVIEW"
    NO_GO = "NO-GO"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class CheckStatus(str, Enum):
    pass_ = "pass"
    fail = "fail"
    warn = "warn"
    not_applicable = "not_applicable"
    error = "error"
