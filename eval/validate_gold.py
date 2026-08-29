"""Offline validation and deterministic matching for ReleaseGuard gold data."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "gold" / "GOLD_SCHEMA.json"
TOKEN_RE = re.compile(r"[^a-z0-9]+")


def normalize_text(s: str) -> str:
    """Apply the frozen matching normalization."""
    return " ".join(TOKEN_RE.sub(" ", s.lower()).split())


def keyword_set_matches(text: str, words: list[str]) -> bool:
    """Return true only when every requested word is a complete normalized token."""
    tokens = set(normalize_text(text).split())
    return all(word in tokens for word in words)


def finding_matches_blocker(
    finding_category: str,
    finding_severity: str,
    finding_title: str,
    finding_claim: str,
    blocker: dict[str, Any],
) -> bool:
    if finding_category != blocker["category"]:
        return False
    allowed = {"critical", "high"} if blocker["severity"] == "critical" else {"critical", "high", "medium"}
    if finding_severity not in allowed:
        return False
    text = f"{finding_title} {finding_claim}"
    return any(keyword_set_matches(text, words) for words in blocker["match_any_of"])


class SchemaValidationError(ValueError):
    pass


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise SchemaValidationError(f"unsupported schema reference: {ref}")
    resolved: Any = root
    for part in ref[2:].split("/"):
        resolved = resolved[part]
    return resolved


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], location: str) -> None:
    schema = _resolve_ref(schema, root)
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{location}: expected object")
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaValidationError(f"{location}: missing required field(s): {', '.join(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise SchemaValidationError(f"{location}: additional field(s): {', '.join(extras)}")
        for key, child_schema in properties.items():
            if key in value:
                _validate(value[key], child_schema, root, f"{location}.{key}")
    elif expected == "array":
        if not isinstance(value, list):
            raise SchemaValidationError(f"{location}: expected array")
        if len(value) < schema.get("minItems", 0):
            raise SchemaValidationError(f"{location}: requires at least {schema['minItems']} item(s)")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate(item, item_schema, root, f"{location}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"{location}: expected string")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"{location}: expected boolean")
    elif expected is not None:
        raise SchemaValidationError(f"{location}: unsupported schema type {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{location}: must be one of {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and re.fullmatch(schema["pattern"], value) is None:
        raise SchemaValidationError(f"{location}: does not match {schema['pattern']}")


def load_gold(path: str | Path) -> dict[str, Any]:
    """Read and validate one gold file against the repository's draft-2020-12 schema."""
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    _validate(payload, schema, schema, "$" )
    return payload


def validate_all(gold_dir: str | Path, cases_dir: str | Path) -> list[str]:
    """Return schema and cross-file consistency problems for the supplied directories."""
    gold_root, cases_root = Path(gold_dir), Path(cases_dir)
    problems: list[str] = []
    gold_files = sorted(gold_root.glob("case_*.json")) if gold_root.exists() else []
    gold_by_case: dict[str, dict[str, Any]] = {}
    for path in gold_files:
        try:
            gold = load_gold(path)
        except (OSError, json.JSONDecodeError, SchemaValidationError) as error:
            problems.append(f"{path}: {error}")
            continue
        case_id = gold["case_id"]
        if path.stem != case_id:
            problems.append(f"{path}: filename stem must match case_id {case_id}")
        if case_id in gold_by_case:
            problems.append(f"duplicate gold case_id: {case_id}")
        gold_by_case[case_id] = gold
        blocker_ids = [blocker["blocker_id"] for blocker in gold["blockers"]]
        if len(blocker_ids) != len(set(blocker_ids)):
            problems.append(f"{path}: duplicate blocker_id")
        if gold["expected_decision"] == "NO-GO" and not any(b["severity"] == "critical" for b in gold["blockers"]):
            problems.append(f"{path}: expected_decision=NO-GO requires a critical blocker")
        if gold["expected_decision"] == "GO" and gold["blockers"]:
            problems.append(f"{path}: expected_decision=GO cannot have blockers")

    case_dirs = sorted(path for path in cases_root.glob("case_*") if path.is_dir()) if cases_root.exists() else []
    case_by_id: dict[str, dict[str, Any]] = {}
    for case_dir in case_dirs:
        metadata_path = case_dir / "case.json"
        if not metadata_path.exists():
            problems.append(f"{case_dir}: missing case.json")
            continue
        try:
            with metadata_path.open(encoding="utf-8") as handle:
                metadata = json.load(handle)
            case_id = metadata["case_id"]
            if not isinstance(metadata["held_out"], bool):
                raise ValueError("held_out must be boolean")
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
            problems.append(f"{metadata_path}: invalid case metadata: {error}")
            continue
        case_by_id[case_id] = metadata

    for case_id, gold in gold_by_case.items():
        if case_id not in case_by_id:
            problems.append(f"gold without corresponding eval/cases/{case_id}: {case_id}")
        else:
            case = case_by_id[case_id]
            if gold["held_out"] != case["held_out"]:
                problems.append(f"{case_id}: held_out differs between gold and case.json")
            if gold["requested_ref"] != case.get("requested_ref"):
                problems.append(f"{case_id}: requested_ref differs between gold and case.json")
    for case_id in case_by_id:
        if case_id not in gold_by_case:
            problems.append(f"case without gold: {case_id}")
    return problems


def main() -> int:
    gold_dir = ROOT / "gold"
    problems = []
    for path in sorted(gold_dir.glob("case_*.json")):
        try:
            load_gold(path)
        except (OSError, json.JSONDecodeError, SchemaValidationError) as error:
            problems.append(f"{path}: {error}")
    if problems:
        print("\n".join(problems))
        return 1
    count = len(list(gold_dir.glob("case_*.json")))
    print(f"OK: {count} gold files valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
