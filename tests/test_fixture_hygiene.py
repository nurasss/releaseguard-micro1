import json
import re
import shutil
from pathlib import Path

from eval.fixture_sha import compute_repo_commit_sha


CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
FIXTURE_SHAS_PATH = CASES_DIR / "FIXTURE_SHAS.json"

LEAK_REGEX = re.compile(
    r"\b(?:defect|bug|fixme|todo|xxx|hack|intentional|deliberate|known issue|workaround)\b",
    re.IGNORECASE,
)


def contains_leak_keyword(text: str) -> bool:
    return bool(LEAK_REGEX.search(text))


def test_case_fixtures_have_no_compiled_python_or_pycache_directories():
    pyc_files = sorted(path for path in CASES_DIR.rglob("*.pyc") if path.is_file())
    pycache_dirs = sorted(path for path in CASES_DIR.rglob("__pycache__") if path.is_dir())
    assert not pyc_files and not pycache_dirs, f"fixture cache artifacts: {pyc_files + pycache_dirs}"


def test_repository_fixture_files_use_lf_only():
    crlf_files = []
    for repo_dir in sorted(CASES_DIR.glob("case_*/repo")):
        for path in repo_dir.rglob("*"):
            if path.is_file() and b"\r\n" in path.read_bytes():
                crlf_files.append(path)
    assert not crlf_files, f"CRLF changes fixture SHA: {crlf_files}"


def test_repository_fixtures_contain_no_leak_keywords():
    leaks = []
    for repo_dir in sorted(CASES_DIR.glob("case_*/repo")):
        for path in repo_dir.rglob("*"):
            if path.is_file() and path.name != "LICENSE":
                text = path.read_text(encoding="utf-8", errors="ignore")
                match = LEAK_REGEX.search(text)
                if match:
                    leaks.append(f"{path}: contains leak keyword {match.group(0)!r}")
    assert not leaks, f"Found leak keywords in repository fixtures:\n" + "\n".join(leaks)


def test_leak_regex_word_boundaries_behavior():
    assert not contains_leak_keyword("Run with --debug to see verbose output.")
    assert not contains_leak_keyword("Join our weekend hackathon.")
    assert not contains_leak_keyword("All todos have been resolved.")
    assert contains_leak_keyword("# Bug: adds instead of multiplies")
    assert contains_leak_keyword("This is a known issue in the upstream service.")


def test_fixture_commit_shas_match_frozen_baseline():
    assert FIXTURE_SHAS_PATH.exists(), "FIXTURE_SHAS.json does not exist"
    frozen_shas = json.loads(FIXTURE_SHAS_PATH.read_text(encoding="utf-8"))
    assert len(frozen_shas) == 12, f"Expected 12 case SHAs, found {len(frozen_shas)}"

    for case_id, expected_sha in frozen_shas.items():
        case_repo_dir = CASES_DIR / case_id / "repo"
        assert case_repo_dir.exists(), f"Case repo dir {case_repo_dir} does not exist"
        actual_sha = compute_repo_commit_sha(case_repo_dir)
        assert (
            actual_sha == expected_sha
        ), f"SHA mismatch for {case_id}: expected {expected_sha}, computed {actual_sha}"


def test_tampering_with_fixture_changes_sha(tmp_path):
    case_repo = CASES_DIR / "case_01" / "repo"
    temp_repo = tmp_path / "case_01_repo"
    shutil.copytree(case_repo, temp_repo)

    original_sha = compute_repo_commit_sha(temp_repo)
    sample_file = next(temp_repo.rglob("*.py"))
    sample_file.write_text(sample_file.read_text(encoding="utf-8") + "\n# change\n", encoding="utf-8")

    tampered_sha = compute_repo_commit_sha(temp_repo)
    assert original_sha != tampered_sha
