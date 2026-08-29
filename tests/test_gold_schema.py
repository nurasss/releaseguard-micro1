# path: tests/test_gold_schema.py
import ast
import json
from pathlib import Path

import pytest

from eval.check_probes import failing_negative_probes, failing_probes
from eval.validate_gold import (
    SchemaValidationError,
    finding_matches_blocker,
    keyword_set_matches,
    load_gold,
    normalize_text,
    validate_all,
)


ROOT = Path(__file__).resolve().parents[1]


def blocker(severity="critical", category="ci", match_any_of=None):
    return {
        "blocker_id": "ci_release_trigger_missing",
        "severity": severity,
        "category": category,
        "description": "test blocker",
        "match_any_of": match_any_of or [["release", "workflow", "trigger"]],
        "acceptable_evidence": [".github/workflows/release.yml"],
    }


def test_normalize_text_cleans_punctuation_and_case():
    assert normalize_text(" CI-RED: Release_Workflow!! ") == "ci red release workflow"


def test_keyword_set_requires_all_words():
    assert keyword_set_matches("release workflow trigger missing", ["release", "workflow"])
    assert not keyword_set_matches("release workflow", ["release", "trigger"])


def test_keyword_ci_is_not_a_substring_match():
    assert not keyword_set_matches("circuit breaker", ["ci"])


def test_keyword_test_is_not_a_substring_match():
    assert not keyword_set_matches("latest artifact", ["test"])


def test_correct_category_critical_and_words_match():
    assert finding_matches_blocker("ci", "critical", "Release workflow", "trigger is missing", blocker())


def test_different_category_does_not_match():
    assert not finding_matches_blocker("build", "critical", "Release workflow", "trigger is missing", blocker())


def test_medium_does_not_match_critical_gold():
    assert not finding_matches_blocker("ci", "medium", "Release workflow", "trigger is missing", blocker("critical"))


def test_medium_matches_high_gold():
    assert finding_matches_blocker("ci", "medium", "Release workflow", "trigger is missing", blocker("high"))


def test_second_match_any_of_set_can_match():
    candidate = blocker(match_any_of=[["release", "workflow", "trigger"], ["release", "branch", "not", "run"]])
    assert finding_matches_blocker("ci", "high", "Release branch", "will not run", candidate)


def test_case_09_loads():
    gold = load_gold(ROOT / "eval" / "gold" / "case_09.json")
    assert gold["case_id"] == "case_09"


def test_all_workspace_cases_validate_cleanly():
    problems = validate_all(ROOT / "eval" / "gold", ROOT / "eval" / "cases")
    assert problems == []


def test_probes_matching_and_rejection():
    assert failing_probes() == []
    assert failing_negative_probes() == []


@pytest.mark.parametrize("case_num", ["07", "08", "09", "10", "11", "12"])
def test_each_case_loads_and_matches_metadata(case_num):
    case_id = f"case_{case_num}"
    gold_path = ROOT / "eval" / "gold" / f"{case_id}.json"
    case_path = ROOT / "eval" / "cases" / case_id / "case.json"

    assert gold_path.exists()
    assert case_path.exists()

    gold = load_gold(gold_path)
    with case_path.open(encoding="utf-8") as f:
        case_meta = json.load(f)

    assert gold["case_id"] == case_id
    assert case_meta["case_id"] == case_id
    assert gold["held_out"] == case_meta["held_out"]
    assert gold["requested_ref"] == case_meta["requested_ref"]


def test_case_11_test_report_source_consistency():
    repo_dir = ROOT / "eval" / "cases" / "case_11" / "repo"
    test_files = list((repo_dir / "tests").glob("test_*.py"))
    all_tests = []
    for tf in test_files:
        tree = ast.parse(tf.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                all_tests.append(node.name)

    report_path = ROOT / "eval" / "cases" / "case_11" / "artifacts" / "test_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert len(test_files) == 3
    assert len(all_tests) == 9
    assert report["total"] == 9
    assert report["passed"] == 6
    assert report["failed"] == 3
    assert len(report["failures"]) == 3

    for failure in report["failures"]:
        assert "test" in failure
        assert "error_type" in failure
        assert "message" in failure
        assert failure["test"] in all_tests


def test_additional_gold_field_is_rejected(tmp_path):
    payload = json.loads((ROOT / "eval" / "gold" / "case_09.json").read_text(encoding="utf-8"))
    payload["unexpected"] = True
    path = tmp_path / "case_09.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="additional field"):
        load_gold(path)


def test_no_go_without_critical_blocker_is_reported(tmp_path):
    gold_dir = tmp_path / "gold"
    cases_dir = tmp_path / "cases"
    gold_dir.mkdir()
    case_dir = cases_dir / "case_09"
    case_dir.mkdir(parents=True)
    payload = json.loads((ROOT / "eval" / "gold" / "case_09.json").read_text(encoding="utf-8"))
    payload["blockers"] = []
    (gold_dir / "case_09.json").write_text(json.dumps(payload), encoding="utf-8")
    (case_dir / "case.json").write_text(json.dumps({"case_id": "case_09", "held_out": True}), encoding="utf-8")
    problems = validate_all(gold_dir, cases_dir)
    assert any("requires a critical blocker" in problem for problem in problems)


def test_gold_filename_must_match_case_id(tmp_path):
    gold_dir = tmp_path / "gold"
    gold_dir.mkdir()
    payload = json.loads((ROOT / "eval" / "gold" / "case_09.json").read_text(encoding="utf-8"))
    (gold_dir / "case_10.json").write_text(json.dumps(payload), encoding="utf-8")
    problems = validate_all(gold_dir, tmp_path / "cases")
    assert any("filename stem must match case_id" in problem for problem in problems)


def test_gold_requested_ref_must_match_case_metadata(tmp_path):
    gold_dir = tmp_path / "gold"
    case_dir = tmp_path / "cases" / "case_09"
    gold_dir.mkdir()
    case_dir.mkdir(parents=True)
    payload = json.loads((ROOT / "eval" / "gold" / "case_09.json").read_text(encoding="utf-8"))
    (gold_dir / "case_09.json").write_text(json.dumps(payload), encoding="utf-8")
    (case_dir / "case.json").write_text(
        json.dumps({"case_id": "case_09", "held_out": True, "requested_ref": "main"}), encoding="utf-8"
    )
    problems = validate_all(gold_dir, tmp_path / "cases")
    assert any("requested_ref differs" in problem for problem in problems)
