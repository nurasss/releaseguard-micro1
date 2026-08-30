# path: app/checks/registry.py
"""Registry that runs every deterministic check (DC-01..DC-10) and collects results."""

from __future__ import annotations

import re

from app.checks.build import check_build_command, check_lockfile_presence
from app.checks.ci import (
    check_ci_latest_run_status,
    check_ci_release_trigger,
    check_ci_workflow_presence,
)
from app.checks.env import check_required_env_vars
from app.checks.migrations import check_migration_execution
from app.checks.release import check_version_metadata
from app.checks.secrets import check_secret_scan
from app.checks.tests import check_test_configuration
from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus
from app.sources.base import RepositorySource, ResolvedRef

# Explicitly out of scope for Phase 1 (deterministic checks): DC-11 (Semgrep/Bandit
# static analysis) is not implemented here.
_ALL_CHECKS = (
    check_test_configuration,
    check_ci_workflow_presence,
    check_ci_release_trigger,
    check_ci_latest_run_status,
    check_version_metadata,
    check_lockfile_presence,
    check_build_command,
    check_required_env_vars,
    check_migration_execution,
    check_secret_scan,
)

_CHECK_ID_RE = re.compile(r"^DC-\d{2}$")


def run_all_checks(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> list[DeterministicCheckResult]:
    """Run every registered deterministic check and return their results.

    A check that raises is never allowed to abort the whole audit run: its
    failure is captured as a DeterministicCheckResult with status=error instead.
    """
    results: list[DeterministicCheckResult] = []

    for check_fn in _ALL_CHECKS:
        try:
            result = check_fn(source, resolved, evidence_store)
        except Exception as exc:  # noqa: BLE001 - deterministic checks must never crash the run
            results.append(
                DeterministicCheckResult(
                    check_id="DC-00",
                    name=getattr(check_fn, "__name__", "unknown_check"),
                    status=CheckStatus.error,
                    details=f"Check {check_fn!r} raised an unexpected error: {exc!r}",
                    evidence_ids=[],
                )
            )
            continue

        if not _CHECK_ID_RE.match(result.check_id):
            raise ValueError(f"Check {check_fn!r} returned invalid check_id {result.check_id!r}")
        results.append(result)

    return results
