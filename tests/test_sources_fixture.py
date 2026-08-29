# path: tests/test_sources_fixture.py
import json
from pathlib import Path

import pytest

from app.sources.base import (
    MAX_READ_FILE_CHARS,
    MAX_READ_FILE_LINES,
    MAX_SEARCH_HITS,
    MAX_TEST_ERROR_MESSAGE_CHARS,
)
from app.sources.errors import (
    FileNotFoundInRepoError,
    PathEscapeError,
    UnknownRefError,
)
from app.sources.fixture import LocalFixtureSource


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
FIXTURE_SHAS = json.loads((CASES_DIR / "FIXTURE_SHAS.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case_id", [f"case_{i:02d}" for i in range(1, 13)])
def test_fixture_source_resolves_ref_to_frozen_commit_sha(case_id: str) -> None:
    case_dir = CASES_DIR / case_id
    case_meta = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    requested_ref = case_meta["requested_ref"]

    source = LocalFixtureSource(case_dir)
    resolved = source.resolve_ref(requested_ref)

    assert resolved.requested_ref == requested_ref
    assert resolved.commit_sha == FIXTURE_SHAS[case_id]
    assert resolved.ref_type in {"branch", "tag", "release", "commit"}


def test_fixture_source_unknown_ref_raises_error() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    with pytest.raises(UnknownRefError, match="not found"):
        source.resolve_ref("non_existent_branch_v9.9.9")


def test_case_json_isolation_and_path_traversal_prevention() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")

    # 1. Traversal to case.json
    with pytest.raises(PathEscapeError):
        source.read_file("../case.json")

    # 2. Deep traversal
    with pytest.raises(PathEscapeError):
        source.read_file("../../etc/passwd")

    # 3. Absolute path (POSIX)
    with pytest.raises(PathEscapeError):
        source.read_file("/etc/passwd")

    # 4. Absolute path (Windows drive)
    with pytest.raises(PathEscapeError):
        source.read_file("C:/Windows/system.ini")

    # 5. Traversal with inner ".."
    with pytest.raises(PathEscapeError):
        source.read_file("src/../../case.json")

    # 6. Non-existent file within repo
    with pytest.raises(FileNotFoundInRepoError):
        source.read_file("non_existent_file.py")


def test_get_tree_is_deterministic_and_sorted() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    tree_1 = source.get_tree()
    tree_2 = source.get_tree()

    assert len(tree_1) > 0
    assert tree_1 == tree_2
    paths = [e.path for e in tree_1]
    assert paths == sorted(paths)


def test_read_file_exact_line_slicing() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    slice_full = source.read_file("pyproject.toml")
    assert slice_full.total_lines > 0

    slice_range = source.read_file("pyproject.toml", start_line=2, end_line=4)
    assert slice_range.start_line == 2
    assert slice_range.end_line == 4
    lines = slice_range.content.splitlines()
    assert len(lines) == 3
    assert not slice_range.truncated


def test_read_file_truncation_limits(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_mock"
    repo_dir = case_dir / "repo"
    artifacts_dir = case_dir / "artifacts"
    repo_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    # Create file with 600 lines (exceeds MAX_READ_FILE_LINES = 400)
    large_file = repo_dir / "large.py"
    large_file.write_text("\n".join(f"# Line {i}" for i in range(1, 601)), encoding="utf-8")

    source = LocalFixtureSource(case_dir)
    slice_res = source.read_file("large.py")
    assert slice_res.total_lines == 600
    assert slice_res.truncated is True
    assert len(slice_res.content.splitlines()) == MAX_READ_FILE_LINES


def test_search_files_filtering_and_limits(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_mock"
    repo_dir = case_dir / "repo"
    artifacts_dir = case_dir / "artifacts"
    repo_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    # Create 70 lines matching pattern
    f1 = repo_dir / "match.py"
    f1.write_text("\n".join(f"TARGET_VAR_{i} = {i}" for i in range(70)), encoding="utf-8")

    source = LocalFixtureSource(case_dir)
    hits = source.search_files("TARGET_VAR")
    assert len(hits) == MAX_SEARCH_HITS
    assert hits[0].path == "match.py"
    assert hits[0].line_number == 1


def test_test_report_error_message_truncation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_mock"
    repo_dir = case_dir / "repo"
    artifacts_dir = case_dir / "artifacts"
    repo_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    very_long_msg = "X" * 1000
    (artifacts_dir / "test_report.json").write_text(
        json.dumps(
            {
                "total": 1,
                "passed": 0,
                "failed": 1,
                "failures": [{"test": "test_fn", "error_type": "AssertionError", "message": very_long_msg}],
            }
        ),
        encoding="utf-8",
    )

    source = LocalFixtureSource(case_dir)
    report = source.get_test_report()
    assert report is not None
    assert len(report["failures"][0]["message"]) == MAX_TEST_ERROR_MESSAGE_CHARS


def test_get_workflow_files_and_metadata() -> None:
    source = LocalFixtureSource(CASES_DIR / "case_01")
    wf_files = source.get_workflow_files()
    assert ".github/workflows/ci.yml" in wf_files

    meta = source.get_repository_metadata()
    assert meta["default_branch"] == "main"
    assert "main" in meta["branches"]
    assert isinstance(meta["tags"], list)
    assert isinstance(meta["releases"], list)
