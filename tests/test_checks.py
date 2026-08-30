# path: tests/test_checks.py
"""Tests for Phase 1 deterministic checks (app/checks/).

Runs every check against the real evaluation fixtures (eval/cases/case_01..case_12)
via LocalFixtureSource, and cross-checks the observed statuses against what each
case's gold blocker (eval/gold/case_XX.json) and description imply. Also includes
a handful of fabricated minimal fixtures to isolate individual checks that no
single real case exercises cleanly on its own.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.checks.build import check_build_command, check_lockfile_presence
from app.checks.ci import (
    check_ci_latest_run_status,
    check_ci_release_trigger,
    check_ci_workflow_presence,
    parse_workflow_triggers,
)
from app.checks.env import check_required_env_vars
from app.checks.migrations import check_migration_execution
from app.checks.registry import run_all_checks
from app.checks.release import check_version_metadata
from app.checks.secrets import check_secret_scan
from app.checks.tests import check_test_configuration
from app.evidence.store import EvidenceStore
from app.schemas.enums import CheckStatus
from app.sources.fixture import LocalFixtureSource

CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
GOLD_DIR = Path(__file__).resolve().parents[1] / "eval" / "gold"


def _load(case_id: str):
    case_dir = CASES_DIR / case_id
    case_meta = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    gold = json.loads((GOLD_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
    source = LocalFixtureSource(case_dir)
    resolved = source.resolve_ref(case_meta["requested_ref"])
    store = EvidenceStore(audit_run_id=f"test-{case_id}", commit_sha=resolved.commit_sha)
    return source, resolved, store, gold


# ---------------------------------------------------------------------------
# Registry: runs cleanly (no exceptions / status=error) across every case.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", [f"case_{i:02d}" for i in range(1, 13)])
def test_run_all_checks_never_errors(case_id: str) -> None:
    source, resolved, store, _ = _load(case_id)
    results = run_all_checks(source, resolved, store)

    check_ids = [r.check_id for r in results]
    assert check_ids == [f"DC-{i:02d}" for i in range(1, 11)]
    for r in results:
        assert r.status != CheckStatus.error, f"{case_id}: {r.check_id} errored: {r.details}"
        for eid in r.evidence_ids:
            assert store.get(eid) is not None


# ---------------------------------------------------------------------------
# DC-01: test configuration / execution
# ---------------------------------------------------------------------------


def test_dc01_case01_clean_passes() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_test_configuration(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc01_case02_failing_test_fails() -> None:
    source, resolved, store, _ = _load("case_02")
    result = check_test_configuration(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "test_calculate_total_applies_tax_rate" in result.details


def test_dc01_case04_no_tests_warns() -> None:
    source, resolved, store, _ = _load("case_04")
    result = check_test_configuration(source, resolved, store)
    assert result.status == CheckStatus.warn


def test_dc01_case11_multiple_failures_fails() -> None:
    source, resolved, store, _ = _load("case_11")
    result = check_test_configuration(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "3 failing" in result.details or "3" in result.details


def test_dc01_case12_integration_tests_excluded_warns() -> None:
    source, resolved, store, _ = _load("case_12")
    result = check_test_configuration(source, resolved, store)
    # test_report.json shows 4/4 passing, but 2 more @pytest.mark.integration tests
    # exist in the repo and are absent from the report -> should be flagged, not a
    # silent pass.
    assert result.status == CheckStatus.warn
    assert "excluded" in result.details or "report only accounts" in result.details


def test_dc01_no_tests_no_config_fabricated(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_fab"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    (case_dir / "repo" / "README.md").write_text("# empty project\n", encoding="utf-8")
    source = LocalFixtureSource(case_dir)
    store = EvidenceStore(audit_run_id="fab", commit_sha="f" * 40)

    class _Resolved:
        requested_ref = "v1.0.0"
        ref_type = "tag"

    result = check_test_configuration(source, _Resolved(), store)
    assert result.status == CheckStatus.warn
    assert "No tests" in result.details


# ---------------------------------------------------------------------------
# DC-02/03/04: CI workflow presence, trigger configuration, latest run status
# ---------------------------------------------------------------------------


def test_dc02_case01_workflow_present() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_ci_workflow_presence(source, resolved, store)
    assert result.status == CheckStatus.pass_
    assert ".github/workflows/ci.yml" in result.details


def test_dc02_case02_workflow_present() -> None:
    # case_02 has a ci.yml but no recorded run for this ref (that absence is a
    # secondary CI signal, not the primary blocker for this case).
    source, resolved, store, _ = _load("case_02")
    result = check_ci_workflow_presence(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc02_no_workflow_dir_warns(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_fab_no_ci"
    (case_dir / "repo").mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    (case_dir / "repo" / "README.md").write_text("# empty project\n", encoding="utf-8")
    source = LocalFixtureSource(case_dir)
    store = EvidenceStore(audit_run_id="fab-no-ci", commit_sha="a" * 40)

    class _Resolved:
        requested_ref = "v1.0.0"
        ref_type = "tag"

    result = check_ci_workflow_presence(source, _Resolved(), store)
    assert result.status == CheckStatus.warn


def test_dc03_case09_release_trigger_missing_fails() -> None:
    source, resolved, store, _ = _load("case_09")
    result = check_ci_release_trigger(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "release.yml" in result.details


def test_dc03_case10_deploy_trigger_matches_tag() -> None:
    source, resolved, store, _ = _load("case_10")
    result = check_ci_release_trigger(source, resolved, store)
    assert result.status == CheckStatus.pass_
    assert "deploy.yml" in result.details


def test_dc03_case01_ci_trigger_matches_tag() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_ci_release_trigger(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc04_case03_ci_run_failed() -> None:
    source, resolved, store, _ = _load("case_03")
    result = check_ci_latest_run_status(source, resolved, store)
    assert result.status == CheckStatus.fail


def test_dc04_case11_ci_run_failed_despite_readme_claims() -> None:
    source, resolved, store, _ = _load("case_11")
    result = check_ci_latest_run_status(source, resolved, store)
    assert result.status == CheckStatus.fail


def test_dc04_case01_ci_run_success() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_ci_latest_run_status(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc04_case02_no_run_recorded_warns() -> None:
    source, resolved, store, _ = _load("case_02")
    result = check_ci_latest_run_status(source, resolved, store)
    assert result.status == CheckStatus.warn


def test_parse_workflow_triggers_block_style_list() -> None:
    content = """
on:
  push:
    branches:
      - main
      - "release/**"
jobs:
  x:
    runs-on: ubuntu-latest
"""
    triggers = parse_workflow_triggers(content)
    assert triggers["has_push"] is True
    assert triggers["push_branches"] == ["main", "release/**"]
    assert triggers["push_tags"] is None


def test_parse_workflow_triggers_inline_list() -> None:
    content = """
on:
  push:
    branches: [main]
    tags: ["v*"]
"""
    triggers = parse_workflow_triggers(content)
    assert triggers["push_branches"] == ["main"]
    assert triggers["push_tags"] == ["v*"]


# ---------------------------------------------------------------------------
# DC-05: release version metadata consistency
# ---------------------------------------------------------------------------


def test_dc05_case07_version_mismatch_fails() -> None:
    source, resolved, store, _ = _load("case_07")
    result = check_version_metadata(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "2.0.3" in result.details
    assert "2.1.0" in result.details


@pytest.mark.parametrize(
    "case_id", ["case_01", "case_02", "case_03", "case_04", "case_05", "case_06", "case_10", "case_12"]
)
def test_dc05_matching_versions_pass(case_id: str) -> None:
    source, resolved, store, _ = _load(case_id)
    result = check_version_metadata(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc05_branch_ref_still_extracts_embedded_version() -> None:
    # case_09's requested ref is "release/v2.4.0" (a branch, not a tag) but still
    # embeds a semantic version that should be compared to the manifest.
    source, resolved, store, _ = _load("case_09")
    result = check_version_metadata(source, resolved, store)
    assert result.status == CheckStatus.pass_


# ---------------------------------------------------------------------------
# DC-06 / DC-07: lockfile presence, build/release command
# ---------------------------------------------------------------------------


def test_dc06_case01_lockfile_present() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_lockfile_presence(source, resolved, store)
    assert result.status == CheckStatus.pass_
    assert "requirements.lock" in result.details


def test_dc06_case02_manifest_without_lockfile_warns() -> None:
    source, resolved, store, _ = _load("case_02")
    result = check_lockfile_presence(source, resolved, store)
    assert result.status == CheckStatus.warn


def test_dc07_case06_broken_build_script_fails() -> None:
    source, resolved, store, _ = _load("case_06")
    result = check_build_command(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "ModuleNotFoundError" in result.details or "exit_code 1" in result.details or "exited with code 1" in result.details


def test_dc07_case01_no_build_command_not_applicable() -> None:
    source, resolved, store, _ = _load("case_01")
    result = check_build_command(source, resolved, store)
    assert result.status == CheckStatus.not_applicable


# ---------------------------------------------------------------------------
# DC-08: required environment variables documented
# ---------------------------------------------------------------------------


def test_dc08_case05_undocumented_required_env_fails() -> None:
    source, resolved, store, _ = _load("case_05")
    result = check_required_env_vars(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "SMTP_HOST" in result.details


def test_dc08_case01_no_required_env_not_applicable() -> None:
    # case_01's env vars are all os.environ.get(..., default) -> optional, not required.
    source, resolved, store, _ = _load("case_01")
    result = check_required_env_vars(source, resolved, store)
    assert result.status == CheckStatus.not_applicable


def test_dc08_documented_required_env_passes(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_fab_env"
    repo = case_dir / "repo"
    (repo / "src").mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    (repo / "src" / "config.py").write_text(
        'import os\nHOST = os.environ["APP_HOST"]\n', encoding="utf-8"
    )
    (repo / "README.md").write_text("Requires `APP_HOST` to be set.\n", encoding="utf-8")

    source = LocalFixtureSource(case_dir)
    store = EvidenceStore(audit_run_id="fab-env", commit_sha="e" * 40)

    class _Resolved:
        requested_ref = "v1.0.0"
        ref_type = "tag"

    result = check_required_env_vars(source, _Resolved(), store)
    assert result.status == CheckStatus.pass_


# ---------------------------------------------------------------------------
# DC-09: migration execution coverage
# ---------------------------------------------------------------------------


def test_dc09_case10_missing_migration_step_fails() -> None:
    source, resolved, store, _ = _load("case_10")
    result = check_migration_execution(source, resolved, store)
    assert result.status == CheckStatus.fail
    assert "0003_add_payment_methods.sql" in result.details


@pytest.mark.parametrize(
    "case_id",
    [f"case_{i:02d}" for i in range(1, 13) if i != 10],
)
def test_dc09_no_migrations_not_applicable(case_id: str) -> None:
    source, resolved, store, _ = _load(case_id)
    result = check_migration_execution(source, resolved, store)
    assert result.status == CheckStatus.not_applicable


def test_dc09_documented_migration_passes(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_fab_migrations"
    repo = case_dir / "repo"
    (repo / "migrations").mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    (repo / "migrations" / "0001_init.sql").write_text("CREATE TABLE x (id INT);\n", encoding="utf-8")
    (repo / "RELEASE.md").write_text(
        "## Deploy steps\n1. Run database migrations: `alembic upgrade head`\n2. Restart service\n",
        encoding="utf-8",
    )

    source = LocalFixtureSource(case_dir)
    store = EvidenceStore(audit_run_id="fab-mig", commit_sha="d" * 40)

    class _Resolved:
        requested_ref = "v1.0.0"
        ref_type = "tag"

    result = check_migration_execution(source, _Resolved(), store)
    assert result.status == CheckStatus.pass_


# ---------------------------------------------------------------------------
# DC-10: secret scan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", [f"case_{i:02d}" for i in range(1, 13)])
def test_dc10_real_fixtures_have_no_secrets(case_id: str) -> None:
    source, resolved, store, _ = _load(case_id)
    result = check_secret_scan(source, resolved, store)
    assert result.status == CheckStatus.pass_


def test_dc10_detects_injected_secret(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_fab_secret"
    repo = case_dir / "repo"
    repo.mkdir(parents=True)
    (case_dir / "artifacts").mkdir()
    synthetic_aws_key = "AKIA" + "ABCDEFGHIJKLMNOP"
    (repo / "settings.py").write_text(
        f'AWS_KEY = "{synthetic_aws_key}"\n', encoding="utf-8"
    )

    source = LocalFixtureSource(case_dir)
    store = EvidenceStore(audit_run_id="fab-secret", commit_sha="c" * 40)

    class _Resolved:
        requested_ref = "v1.0.0"
        ref_type = "tag"

    result = check_secret_scan(source, _Resolved(), store)
    assert result.status == CheckStatus.fail
    assert "AWS Access Key" in result.details
    assert synthetic_aws_key not in result.details  # must not leak the raw secret
