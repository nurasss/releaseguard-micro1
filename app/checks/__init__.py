# path: app/checks/__init__.py
"""Deterministic (non-LLM) evidence-driven checks for ReleaseGuard Phase 1.

Each module exposes one or more `check_*` functions with a uniform signature:

    def check_x(source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore) -> DeterministicCheckResult

`app.checks.registry.run_all_checks` runs every registered check and returns
the full list of `DeterministicCheckResult` objects.
"""

from app.checks.registry import run_all_checks

__all__ = ["run_all_checks"]
