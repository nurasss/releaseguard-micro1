# path: app/checks/ci.py
"""DC-02: CI workflow presence.
DC-03: whether the applicable workflow is configured to trigger on the release ref.
DC-04: latest recorded CI run status for that ref.
"""

from __future__ import annotations

import fnmatch
import re

from app.evidence.store import EvidenceStore
from app.schemas.audit import DeterministicCheckResult
from app.schemas.enums import CheckStatus, SourceType
from app.sources.base import RepositorySource, ResolvedRef

_RELEASE_KEYWORDS = ("release", "deploy", "publish", "cd")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _collect_block(lines: list[str], idx: int, indent: int) -> list[str]:
    block: list[str] = []
    for line in lines[idx + 1 :]:
        if line.strip() == "":
            block.append(line)
            continue
        if _indent(line) <= indent:
            break
        block.append(line)
    return block


def parse_workflow_triggers(content: str) -> dict:
    """Best-effort parse of a GitHub Actions workflow's `on:` push trigger.

    Returns {"has_push": bool, "push_branches": list[str] | None, "push_tags": list[str] | None}
    where None for branches/tags means the push trigger is present but unrestricted
    (i.e. matches any ref).
    """
    lines = content.splitlines()
    result: dict = {"has_push": False, "push_branches": None, "push_tags": None}

    push_idx = None
    push_indent = None
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)push:\s*(.*)$", line)
        if m:
            push_idx = i
            push_indent = len(m.group(1))
            break

    if push_idx is None:
        m = re.search(r"^\s*on:\s*(.*)$", content, re.MULTILINE)
        if m and "push" in m.group(1):
            result["has_push"] = True
        return result

    result["has_push"] = True
    block = _collect_block(lines, push_idx, push_indent)

    def _find_and_parse(key: str) -> list[str] | None:
        for offset, line in enumerate(block):
            m = re.match(rf"^(\s*){key}:\s*(.*)$", line)
            if not m:
                continue
            key_indent = len(m.group(1))
            inline = m.group(2).strip()
            if inline.startswith("["):
                inner = inline.strip("[]")
                return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
            if inline and not inline.startswith("#"):
                return [inline.strip("'\"")]
            items: list[str] = []
            for line2 in block[offset + 1 :]:
                if line2.strip() == "":
                    continue
                if _indent(line2) <= key_indent:
                    break
                stripped = line2.strip()
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip().strip("'\""))
            return items
        return None

    result["push_branches"] = _find_and_parse("branches")
    result["push_tags"] = _find_and_parse("tags")
    return result


def _select_release_workflows(workflow_files: list[str]) -> list[str]:
    candidates = [
        f for f in workflow_files if any(k in f.lower().rsplit("/", 1)[-1] for k in _RELEASE_KEYWORDS)
    ]
    return candidates or list(workflow_files)


def check_ci_workflow_presence(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    workflow_files = source.get_workflow_files()

    if not workflow_files:
        ev = evidence_store.add(
            source_type=SourceType.deterministic_check,
            source_path="<repository tree>",
            summary="No GitHub Actions workflow files found",
            payload={"workflow_files": []},
        )
        return DeterministicCheckResult(
            check_id="DC-02",
            name="CI workflow presence",
            status=CheckStatus.warn,
            details="No workflow files were found under .github/workflows/.",
            evidence_ids=[ev.id],
        )

    ev = evidence_store.add(
        source_type=SourceType.github_actions,
        source_path=".github/workflows",
        summary=f"Found {len(workflow_files)} workflow file(s)",
        payload={"workflow_files": workflow_files},
    )
    return DeterministicCheckResult(
        check_id="DC-02",
        name="CI workflow presence",
        status=CheckStatus.pass_,
        details=f"Found {len(workflow_files)} workflow file(s): {workflow_files}.",
        evidence_ids=[ev.id],
    )


def check_ci_release_trigger(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    workflow_files = source.get_workflow_files()
    if not workflow_files:
        return DeterministicCheckResult(
            check_id="DC-03",
            name="CI release-ref trigger configuration",
            status=CheckStatus.not_applicable,
            details="No workflow files found; cannot evaluate release trigger configuration.",
            evidence_ids=[],
        )

    if resolved.ref_type not in ("branch", "tag", "release"):
        return DeterministicCheckResult(
            check_id="DC-03",
            name="CI release-ref trigger configuration",
            status=CheckStatus.not_applicable,
            details=f"Requested ref resolved to ref_type={resolved.ref_type!r}; trigger matching is not applicable.",
            evidence_ids=[],
        )

    ref_name = resolved.requested_ref
    targets = _select_release_workflows(workflow_files)

    evidence_ids: list[str] = []
    matched: list[str] = []
    unmatched: list[str] = []

    for wf in targets:
        try:
            content = source.read_file(wf).content
        except Exception:
            continue

        triggers = parse_workflow_triggers(content)
        ev = evidence_store.add(
            source_type=SourceType.github_actions,
            source_path=wf,
            summary=f"Parsed push trigger configuration for {wf}",
            payload={"triggers": triggers},
            content=content,
        )
        evidence_ids.append(ev.id)

        if not triggers["has_push"]:
            unmatched.append(f"{wf}: no push trigger configured")
            continue

        patterns = triggers["push_branches"] if resolved.ref_type == "branch" else triggers["push_tags"]

        if patterns is None:
            matched.append(wf)
        elif any(fnmatch.fnmatch(ref_name, p) for p in patterns):
            matched.append(wf)
        else:
            unmatched.append(f"{wf}: push trigger restricted to {patterns}, does not include {ref_name!r}")

    if matched:
        return DeterministicCheckResult(
            check_id="DC-03",
            name="CI release-ref trigger configuration",
            status=CheckStatus.pass_,
            details=f"Workflow(s) {matched} are configured to trigger for ref {ref_name!r}.",
            evidence_ids=evidence_ids,
        )

    return DeterministicCheckResult(
        check_id="DC-03",
        name="CI release-ref trigger configuration",
        status=CheckStatus.fail,
        details=(
            f"No applicable workflow among {targets} is configured to trigger for ref "
            f"{ref_name!r}: {'; '.join(unmatched) if unmatched else 'no matching trigger found'}."
        ),
        evidence_ids=evidence_ids,
    )


def check_ci_latest_run_status(
    source: RepositorySource, resolved: ResolvedRef, evidence_store: EvidenceStore
) -> DeterministicCheckResult:
    runs = source.get_workflow_runs()
    ref_name = resolved.requested_ref
    matching = [r for r in runs if r.get("head_branch") == ref_name]

    if not matching:
        ev = evidence_store.add(
            source_type=SourceType.github_actions,
            source_path="github_actions_runs",
            summary=f"No recorded CI run found for ref {ref_name!r}",
            payload={"all_runs": runs, "requested_ref": ref_name},
        )
        return DeterministicCheckResult(
            check_id="DC-04",
            name="Latest CI run status for release ref",
            status=CheckStatus.warn,
            details=f"No GitHub Actions run was recorded for ref {ref_name!r}.",
            evidence_ids=[ev.id],
        )

    matching.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    latest = matching[0]
    conclusion = latest.get("conclusion", "")

    ev = evidence_store.add(
        source_type=SourceType.github_actions,
        source_path="github_actions_runs",
        summary=f"Latest CI run for ref {ref_name!r}: conclusion={conclusion!r}",
        payload={"latest_run": latest, "requested_ref": ref_name},
    )

    if conclusion == "success":
        status = CheckStatus.pass_
        details = f"Latest recorded CI run for ref {ref_name!r} has conclusion=success."
    elif conclusion == "failure":
        status = CheckStatus.fail
        details = f"Latest recorded CI run for ref {ref_name!r} has conclusion=failure."
    else:
        status = CheckStatus.warn
        details = f"Latest recorded CI run for ref {ref_name!r} has an inconclusive conclusion={conclusion!r}."

    return DeterministicCheckResult(
        check_id="DC-04",
        name="Latest CI run status for release ref",
        status=status,
        details=details,
        evidence_ids=[ev.id],
    )
