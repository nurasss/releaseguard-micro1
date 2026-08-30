# ReleaseGuard frozen evaluation protocol

`FROZEN_AT: 2026-08-29`

`MODEL_ID: gemini-2.5-flash`  ·  `PROMPT_VERSION: p1`  ·  `TOOLSET: 8 read-only tools`

The model is fixed here because it must be identical for B1 and for the final
system; changing it invalidates every comparison made under this protocol. It was
selected on a measured runtime constraint, not on scores: on a trivial request
`gemini-2.5-flash` answered in 1.3 s while `gemini-3.7-flash` took 23.3 s, and at
roughly ten model calls per audit the slower model cannot meet the five-minute
per-fixture target in NFR-08. Results on a stronger model may differ, and that
limitation is reported alongside the numbers rather than hidden.

This protocol evaluates a read-only ReleaseGuard audit against an official B1 baseline on 12 synthetic cases. Gold data is never available to either system during an audit.

The word **official** applies only to a result whose metadata has
`execution_mode: live_provider` and whose baseline and final use the same live
model/provider. The default local Make targets intentionally use
`execution_mode: offline_fixture` so a clean checkout can exercise the full
pipeline without credentials. Those fixture results are engineering smoke
measurements, not official LLM benchmark results, and must not be used to claim
the hackathon baseline/final improvement gate.

## 1. Primary metric

The primary metric is Critical Blocker Recall (CBR):

`CBR = correctly detected known critical blockers / all known critical blockers`.

CBR is recall rather than precision because, for a release engineer, a missed real release blocker costs more than an extra suspicion that a human can dismiss in a minute.

## 2. Finding-to-gold-blocker matching rule

A gold blocker `B` is **detected** if the report contains at least one finding `F` for which all conditions hold:

1. `F.category == B.category`.
2. If `B.severity == critical`, `F.severity` is `critical` or `high`. If `B.severity == high`, `F.severity` is `critical`, `high`, or `medium`.
3. `normalize(F.title + " " + F.claim)` contains every word in at least one word set in `B.match_any_of`.

`normalize(s)` lowercases `s`, replaces every character outside `[a-z0-9]` with one space, and collapses consecutive spaces. A word is present only as a complete normalized token, never as a substring.

Evidence is not a matching condition. B1 is not required to cite evidence; including evidence in recall would measure compliance with ReleaseGuard's own output contract instead of whether the system found the problem, artificially increasing the apparent gap from B1. Evidence quality is measured separately in Section 4. The identical matcher is applied to B1 and final reports without exceptions.

One finding may close at most one gold blocker. Apply the following assignment algorithm exactly:

```text
assigned = {}
for B in sorted(gold.blockers, key=blocker_id):
    candidates = [F for F in report.findings if finding_matches_blocker(F, B) and F.id not in assigned]
    if candidates:
        F* = max(candidates, key=(F.confidence, -numeric(F.id)))   # higher confidence; on a tie, smaller F.id
        assigned[F*.id] = B.blocker_id
detected = set(assigned.values())
```

The algorithm is deterministic and produces the same result independently of the order of findings in the report.

### Keyword calibration and its limits

`match_any_of` sets were expanded once using 33 positive probes written independently of the gold authors before any system run. Negative probes guard that expansion against excessive broadening. Narrow keywords would turn Critical Blocker Recall into a measure of vocabulary overlap rather than detection quality. After the freeze, the sets do not change; any change requires an entry in `docs/IMPROVEMENT_CHANGELOG.md` and recomputation of all prior runs. Keyword matching can still undercount an unusually phrased but correct finding. This limitation applies equally to baseline and final.

## 3. False positives

A `critical` or `high` finding is a false positive when it matches no gold blocker and matches no entry in that case's `acceptable_extra_findings`. Findings with severity `medium`, `low`, or `info` are excluded from precision entirely because they do not block a release.

A trap hit is a `critical` or `high` finding whose title plus claim matches `match_any_of` for any entry in the case's `forbidden_findings`. It is recorded in the separate `trap_hits` counter; it does not affect CBR and does not cancel the same finding's false-positive status. One finding can therefore be both a false positive and a trap hit. Trap hits identify pre-known traps: plausible but evidence-unconfirmed claims.

## 4. Metrics and aggregation

All metrics are reported separately for development (cases 01--08), held-out (cases 09--12), and all cases. CBR is micro-averaged: it is the sum of detected critical blockers divided by the sum of critical blockers across the selected cases, not the mean of per-case recalls, because cases contain different numbers of blockers.

| Metric | Numerator / denominator | Aggregation |
| --- | --- | --- |
| Critical Blocker Recall (primary) | detected gold blockers with `severity=critical` / all gold blockers with `severity=critical` | Micro |
| High Blocker Recall | detected gold blockers with `severity=high` / all gold blockers with `severity=high` | Micro |
| Precision | matched `critical`/`high` findings or acceptable extra `critical`/`high` findings / all reported `critical`/`high` findings | Micro |
| F1 | `2 * precision * recall / (precision + recall)`, where recall is CBR; zero if the denominator is zero | Computed from micro values |
| Decision Accuracy | scheduled cases whose `decision_actual == decision_expected` / all scheduled cases in the slice | Macro (per case) |
| Evidence Coverage | findings with a non-empty `evidence_ids` list whose every ID resolves to evidence with the case `source_ref` / all findings | Micro |
| Critical Evidence Coverage | `critical`/`high` findings with non-empty, fully resolving `evidence_ids` / all `critical`/`high` findings | Micro |
| Unsupported Critical Findings | count of `critical`/`high` findings with empty `evidence_ids` or at least one non-resolving ID | Absolute total |
| Trap Hits | number of `critical`/`high` findings that meet the Section 3 trap-hit definition | Absolute total |
| Successful Run Rate | cases with `status=success` and valid structured output before timeout / all scheduled cases | Macro (per case) |
| Runtime per case | wall-clock audit milliseconds for each case | Per case; median and mean may be reported only as descriptive values |
| Cost per case | estimated model/tool cost charged to one case | Per case; total is the sum |

High blockers are deliberately excluded from CBR by definition, so High Blocker Recall is reported separately; otherwise missed high blockers would not be visible in any recall metric. For Evidence Coverage, an evidence ID resolves only when it identifies an evidence item returned for that case and that item has the case immutable SHA as `source_ref`. A failed case contributes zero detected blockers and an incorrect decision; it remains in all micro denominators. Failed and timed-out cases remain in the Decision Accuracy denominator, because otherwise a timeout on a difficult case would improve the metric.

## 5. Failure policy

The timeout is 300 seconds per case. A timeout marks the case `failed`; every gold blocker in it is missed and its decision is incorrect. Invalid structured output has the same consequence. On a tool error, the system must return a partial or failed audit and must not invent a conclusion. A fabricated finding when the required tool is unavailable is recorded separately as a system integrity failure. A Verifier timeout, provider error, or malformed JSON never confirms a finding: that finding becomes `uncertain`.

## 6. Same-input policy

B1 and final receive byte-identical snapshots, the same resolved commit SHA, the same read-only tools, and the same `AuditReport` output contract. Only prompt and orchestration differ. The model identifier and model version are fixed for a comparison and recorded in every run.

## 7. Immutable SHA for local fixtures

For every file under `eval/cases/case_XX/repo/`, take its relative path using forward slashes and the SHA-256 of its bytes. Form lines `<relpath>:<sha256hex>`, sort them lexicographically by `relpath`, join them with `\n`, SHA-256 the joined bytes, and use the first 40 hexadecimal characters as `commit_sha`. Empty directories are ignored. Files outside `repo/` do not enter the hash.

This SHA must be identical on repeat runs on every machine. It is the `source_ref` for every evidence item in the case.

## 8. Fixture layout

```text
eval/cases/case_XX/case.json
  metadata: case_id, name, requested_ref, held_out, description, notes_for_humans
eval/cases/case_XX/repo/
  repository contents that would actually exist in GitHub
eval/cases/case_XX/artifacts/
  repository_metadata.json  default_branch, branches[], description, tags[], releases[], topics
  github_actions_runs.json  workflow_name, path, head_branch, event, conclusion, created_at, html_url
  test_report.json          optional: total, passed, failed, failures[]
  build_report.json         optional: command, exit_code, stderr_tail
eval/gold/case_XX.json
  gold data; inaccessible to the agent
```

`repository_metadata.json.branches` is mandatory and always includes `default_branch`. The case `requested_ref` must be present in at least one of `branches`, `tags`, or `releases`; otherwise the audit cannot formally start. `github_actions_runs.json.conclusion` is one of `success`, `failure`, `cancelled`, or `null`. Artifacts model GitHub API responses or retained CI results; they are not part of `repo/` and never enter the SHA. The agent sees only `repo/` and normalized representations of `artifacts/`, never their harness paths. `case.json` is harness metadata and is never passed to the agent: it can contain plain-language defect descriptions, whose disclosure would invalidate the case. This separation preserves the distinction found in a real GitHub repository.

## 9. Case catalogue

| case_id | Short name | Ground truth | expected_decision | held_out |
| --- | --- | --- | --- | --- |
| case_01 | Clean release | No blocker | GO | no |
| case_02 | Broken unit test | Critical failing unit test | NO-GO | no |
| case_03 | CI red | Critical required CI failure | NO-GO | no |
| case_04 | No tests | High blocker: tests are absent, a serious risk but not a proven breakage | REVIEW | no |
| case_05 | Missing required env | Critical required release environment setting is absent | NO-GO | no |
| case_06 | Broken build script | Critical release build command failure | NO-GO | no |
| case_07 | Version mismatch | Critical release version metadata conflict | NO-GO | no |
| case_08 | Stale generated artifact | High blocker: generated release artifact is stale | REVIEW | no |
| case_09 | Misconfigured workflow | Critical release workflow does not run for the release branch or tag | NO-GO | yes |
| case_10 | Missing migration step | Critical required migration step is absent | NO-GO | yes |
| case_11 | Conflicting signals | Critical conflicting release signals prevent a safe release | NO-GO | yes |
| case_12 | Challenging | Critical integration path is not actually tested despite green CI | NO-GO | yes |

Cases 01--08 are development cases. Cases 09--12 are held-out and are not used for manual prompt tuning. Results for all 12 cases are published.

### Decision distribution and its floor

Expected decisions are 1 GO (`case_01`), 2 REVIEW (`case_04`, `case_08`), and 9 NO-GO. Therefore the trivial "always NO-GO" policy yields Decision Accuracy = 0.75; every published figure must exceed this floor. The distribution is skewed because the twelve-case set is fixed by the domain rather than selected to balance a metric. Decision Accuracy is therefore a secondary metric, not the primary metric.

## 10. Freeze rule

After the first main experiment run, the primary-metric formula, matching rule, and case set do not change. Any change requires a dated entry in `docs/IMPROVEMENT_CHANGELOG.md` stating the reason and recomputing every prior run under the changed protocol.

## 11. Machine-readable `make evaluate` result

`make evaluate` writes `eval/results/<run_label>/results.json`. Its top-level object contains `meta`, `per_case`, and `aggregate`.

```json
{
  "meta": {
    "run_label": "baseline_2026_08_29",
    "generated_at_utc": "2026-08-29T00:00:00Z",
    "mode": "baseline",
      "model_id": "example-model-2026-08-01",
      "execution_mode": "live_provider",
      "provider": "google",
      "prompt_version": "b1-v1",
    "system_version": "releaseguard-v1",
    "spec_version": "1.0",
    "frozen_at": "<YYYY-MM-DD>",
    "cases_total": 12,
    "timeout_s": 300
  },
  "per_case": [
    {
      "case_id": "case_09",
      "mode": "baseline",
      "commit_sha": "0123456789012345678901234567890123456789",
      "audit_run_id": "audit_case_09_0001",
      "decision_expected": "NO-GO",
      "decision_actual": "NO-GO",
      "matched_blockers": ["ci_release_trigger_missing"],
      "missed_blockers": [],
      "false_positives": [],
      "evidence_coverage": 1.0,
      "critical_evidence_coverage": 1.0,
      "unsupported_critical": 0,
      "trap_hits": 0,
      "blockers_total": 1,
      "runtime_ms": 1234,
      "estimated_cost": 0.01,
      "status": "success"
    }
  ],
  "aggregate": {
    "development": {"cbr": 0.0, "high_blocker_recall": 0.0, "precision": 0.0, "f1": 0.0, "decision_accuracy": 0.0, "evidence_coverage": 0.0, "critical_evidence_coverage": 0.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 0.0, "total_runtime_ms": 0, "total_cost": 0.0},
    "held_out": {"cbr": 0.0, "high_blocker_recall": 0.0, "precision": 0.0, "f1": 0.0, "decision_accuracy": 0.0, "evidence_coverage": 0.0, "critical_evidence_coverage": 0.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 0.0, "total_runtime_ms": 0, "total_cost": 0.0},
    "all": {"cbr": 0.0, "high_blocker_recall": 0.0, "precision": 0.0, "f1": 0.0, "decision_accuracy": 0.0, "evidence_coverage": 0.0, "critical_evidence_coverage": 0.0, "unsupported_critical_total": 0, "trap_hits_total": 0, "successful_run_rate": 0.0, "total_runtime_ms": 0, "total_cost": 0.0}
  }
}
```

`mode` is `baseline` or `final`. `blockers_total` is the number of critical gold blockers in that case. Each aggregate slice contains every listed metric, with `total_runtime_ms` and `total_cost` as sums over that slice.
