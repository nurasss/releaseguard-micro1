# Reproduce ReleaseGuard

## Prerequisites

- Python 3.11 or newer
- Docker, only for the image-build check
- A checkout of this repository at the submission commit

The fixture evaluation does not require Gemini or GitHub credentials.

## Clean deterministic run

Run from the repository root:

```bash
make setup
make test
make baseline
make evaluate
make ablations
make demo CASE=case_12
python scripts/package_submission.py
.venv/bin/python scripts/verify_submission_zip.py dist/releaseguard_submission.zip
```

`make setup` creates `.venv` if needed, installs the exact versions from
`requirements.lock`, and installs the project without resolving a second set
of dependencies. Subsequent Make targets invoke `.venv/bin/python` directly.

The evaluation targets set `RG_OFFLINE_MODE=1`. They run the complete
repository-source, evidence, Analyzer, Verifier, policy, persistence, and
scoring path against the frozen fixtures. The model is reported as
`releaseguard-offline-v1` and the result metadata says `execution_mode:
offline_fixture`.

## Outputs

- `eval/results/<label>/results.json`: machine-readable per-case and aggregate
  metrics.
- `eval/results/<final-label>/comparison.json` and `comparison.md`: baseline
  versus final deltas, when a baseline is present.
- `runs/<audit-run-id>/`: redacted report, Markdown report, run metadata, and
  content-free `snapshot.json`.
- `trajectories/<audit-run-id>.jsonl`: redacted, bounded agent trajectory.
- `submission/`: curated artifacts selected by
  `scripts/prepare_submission.py`.
- `dist/releaseguard_submission.zip`: secrets-free archive.

Local `eval/results/`, `runs/`, and `trajectories/` are runtime output and are
not source-of-truth benchmark data. The packager includes only the selected
copies under `submission/`.

## Quality gates

After baseline and final evaluation:

```bash
.venv/bin/python scripts/check_quality_gates.py
```

The checker uses all-case aggregate metrics and records PASS/FAIL in
`submission/results/quality_gates.json`. The gates are:

| Gate | Requirement |
|---|---:|
| Critical Blocker Recall | ≥ 0.85 |
| Improvement over baseline | ≥ 0.20 absolute |
| Critical evidence coverage | 1.00 |
| Unsupported critical findings | 0 |
| Successful run rate | ≥ 0.95 |

If a gate fails, the result is retained and the failure is reported; no metric
is silently substituted or removed.

## Live provider run

Only run this when a valid Gemini key and quota are intentionally provisioned:

```bash
RG_OFFLINE_MODE=0 .venv/bin/python -m eval.run --mode baseline --label baseline_live
RG_OFFLINE_MODE=0 .venv/bin/python -m eval.run --mode final --label final_live
```

Do not combine live-provider and offline-fixture outputs in one comparison.
Record the provider/model, prompt version, immutable commit SHA, per-case
status, and any quota failures alongside the live results.
