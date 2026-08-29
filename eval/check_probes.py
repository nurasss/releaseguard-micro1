"""Check that every gold blocker matches all independently authored probe phrasings.

A probe is a plausible wording of a CORRECT finding for a known blocker. If a probe
fails to match, the blocker's match_any_of is too narrow: a system that genuinely
found the problem would score zero for it, turning Critical Blocker Recall into a
measurement of vocabulary overlap rather than detection quality.

Probes are harness data. They are never shown to any agent and never enter an audit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from eval.validate_gold import keyword_set_matches  # noqa: E402

PROBES_PATH = ROOT / "probes" / "match_probes.json"
GOLD_DIR = ROOT / "gold"


def load_probes(kind: str = "probes") -> dict[str, list[tuple[str, str]]]:
    payload = json.loads(PROBES_PATH.read_text(encoding="utf-8"))
    return {
        case_id: [(item[0], item[1]) for item in items]
        for case_id, items in payload[kind].items()
    }


def failing_probes() -> list[str]:
    """Return one message per probe that no match_any_of set covers."""
    failures: list[str] = []
    for case_id, probes in sorted(load_probes().items()):
        gold_path = GOLD_DIR / f"{case_id}.json"
        if not gold_path.exists():
            failures.append(f"{case_id}: gold file is missing")
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        blockers = gold["blockers"]
        if not blockers:
            failures.append(f"{case_id}: probes exist but gold declares no blocker")
            continue
        for title, claim in probes:
            text = f"{title} {claim}"
            covered = any(
                keyword_set_matches(text, word_set)
                for blocker in blockers
                for word_set in blocker["match_any_of"]
            )
            if not covered:
                failures.append(f"{case_id}: no match_any_of set covers probe {title!r}")
    return failures


def failing_negative_probes() -> list[str]:
    """Return one message per negative probe that any blocker keyword set matches."""
    failures: list[str] = []
    for case_id, probes in sorted(load_probes("negative_probes").items()):
        gold_path = GOLD_DIR / f"{case_id}.json"
        if not gold_path.exists():
            failures.append(f"{case_id}: gold file is missing")
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        for title, claim in probes:
            text = f"{title} {claim}"
            matched = any(
                keyword_set_matches(text, word_set)
                for blocker in gold["blockers"]
                for word_set in blocker["match_any_of"]
            )
            if matched:
                failures.append(f"{case_id}: negative probe incorrectly matches a blocker: {title!r}")
    return failures


def main() -> int:
    positive_failures = failing_probes()
    negative_failures = failing_negative_probes()
    failures = positive_failures + negative_failures
    positive_total = sum(len(v) for v in load_probes().values())
    negative_total = sum(len(v) for v in load_probes("negative_probes").values())
    if failures:
        print(f"{len(failures)} probe checks failed out of {positive_total} positive and {negative_total} negative probes:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"OK: all {positive_total} positive probes matched and all {negative_total} negative probes rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
