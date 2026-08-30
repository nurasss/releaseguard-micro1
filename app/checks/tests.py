# path: app/checks/tests.py
"""DC-01: test configuration / test directory presence and execution status."""

from __future__ import annotations

import re

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

_TEST_DIR_PREFIXES = ("tests/", "test/")
_TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py)$")
_TEST_CONFIG_FILENAMES = {"pytest.ini", "tox.ini"}
_TEST_DEF_RE = r"^\s*(async\s+)?def test_"


def _looks_like_test_file(path: str) -> bool:
    if path.startswith(_TEST_DIR_PREFIXES):
        return True
    return bool(_TEST_FILE_RE.search(path))


def _has_test_config(source: RepositorySource, tree_paths: set[str]) -> bool:
    if tree_paths & _TEST_CONFIG_FILENAMES:
        return True
    for candidate in ("pyproject.toml", "setup.cfg"):
        if candidate in tree_paths:
            try:
                content = source.read_file(candidate).content
            except Exception:
                continue
            if "pytest" in content.lower():
                return True
    return False


def check_test_configuration(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    tree = source.get_tree()
    tree_paths = {e.path for e in tree}
    test_files = sorted(e.path for e in tree if _looks_like_test_file(e.path))
    has_config = _has_test_config(source, tree_paths)

    if not test_files and not has_config:
        ev = evidence_store.add(
            source_type=SourceType.deterministic_check,
            source_path="<repository tree>",
            summary="No test directory, test files, or test configuration found",
            payload={"test_files": [], "has_test_config": False},
        )
        return DeterministicCheckResult(
            check_id="DC-01",
            name="Test configuration and execution",
            status=CheckStatus.warn,
            details=(
                "No tests/ directory, test_*.py / *_test.py files, or recognized test "
                "configuration (pytest.ini, tox.ini, [tool.pytest] section) were found in "
                "the repository tree. Test coverage cannot be verified."
            ),
            evidence_ids=[ev.id],
        )

    discovered_defs = 0
    if test_files:
        hits = source.search_files(_TEST_DEF_RE, glob=None)
        discovered_defs = sum(1 for h in hits if h.path in test_files)

    report = source.get_test_report()

    if report is not None:
        ev = evidence_store.add(
            source_type=SourceType.test_result,
            source_path="test_report",
            summary=f"Test report: {report.get('passed', 0)}/{report.get('total', 0)} passed, "
            f"{report.get('failed', 0)} failed",
            payload={
                "report": report,
                "test_files": test_files,
                "discovered_test_defs": discovered_defs,
            },
        )
        evidence_ids = [ev.id]

        if report.get("failed", 0) > 0:
            failing = ", ".join(f.get("test", "?") for f in report.get("failures", []))
            return DeterministicCheckResult(
                check_id="DC-01",
                name="Test configuration and execution",
                status=CheckStatus.fail,
                details=(
                    f"Test report records {report.get('failed', 0)} failing test(s) out of "
                    f"{report.get('total', 0)}: {failing}."
                ),
                evidence_ids=evidence_ids,
            )

        total = report.get("total", 0)
        if discovered_defs and total and discovered_defs > total:
            return DeterministicCheckResult(
                check_id="DC-01",
                name="Test configuration and execution",
                status=CheckStatus.warn,
                details=(
                    f"Repository contains {discovered_defs} test function(s) across "
                    f"{len(test_files)} test file(s) ({test_files}), but the latest test "
                    f"report only accounts for {total} test(s). Some tests may be excluded "
                    "from execution (e.g. by a marker filter)."
                ),
                evidence_ids=evidence_ids,
            )

        return DeterministicCheckResult(
            check_id="DC-01",
            name="Test configuration and execution",
            status=CheckStatus.pass_,
            details=(
                f"Test suite present ({len(test_files)} test file(s)) and latest test report "
                f"shows {report.get('passed', 0)}/{total} passing with 0 failures."
            ),
            evidence_ids=evidence_ids,
        )

    summary = f"Found {len(test_files)} test file(s); no execution report available"
    ev = evidence_store.add(
        source_type=SourceType.deterministic_check,
        source_path="<repository tree>",
        summary=summary,
        payload={"test_files": test_files, "discovered_test_defs": discovered_defs},
    )
    detail_files = f" (e.g. {test_files[0]})" if test_files else ""
    return DeterministicCheckResult(
        check_id="DC-01",
        name="Test configuration and execution",
        status=CheckStatus.pass_,
        details=(
            f"Found {len(test_files)} test file(s){detail_files} and/or recognized test "
            "configuration. No test execution report was available to verify pass/fail status."
        ),
        evidence_ids=[ev.id],
    )
