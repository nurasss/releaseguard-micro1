# Reproduce ReleaseGuard

## Prerequisites

- Python 3.11 or newer
- Docker, only for the image-build check
- A checkout of this repository at the submission commit

The fixture evaluation does not require Gemini or GitHub credentials.

## Frozen versions and provenance

- Project requirement: Python `>=3.11` (`pyproject.toml`); the reference run
  used the repository `.venv` interpreter.
- Dependency versions: every runtime and development pin is recorded with
  `==` in `requirements.lock`; `make setup` installs that file first.
- Live model ID: `gemini-2.5-flash`; fixture model ID:
  `releaseguard-offline-v1`.
- Evaluation protocol: `eval/EVALUATION_SPEC.md`, frozen at `2026-08-29`.

The default commands are deliberately fixture-mode commands. Their outputs
include `execution_mode: offline_fixture` and can validate code paths, schema,
security, scoring, and packaging without pretending to be a live LLM result.

## Clean deterministic run

Run from the repository root:

```bash
make setup
make test
make baseline
make evaluate
make ablations
make demo CASE=case_12
.venv/bin/python scripts/package_submission.py
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

The full local path takes approximately 2-5 minutes from a warm checkout
(mostly setup/install time; the evaluation commands themselves are under a
minute on the reference host). A cold dependency download can take roughly
5-10 minutes depending on the package mirror. Fixture execution costs
`$0.0000`: it makes no provider calls. A live Gemini reproduction has no fixed
cost in this repository; cost depends on token usage and the configured Gemini
rate, and the run records `estimated_cost` per case.

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

For the checked-in fixture pair the numeric gates pass only within the
`offline_fixture_simulation` scope. They are not an official LLM pass because
the baseline/final pair was not produced by a live provider.

## Live provider run

Only run this when a valid Gemini key and quota are intentionally provisioned:

```bash
make baseline-live
make evaluate-live
```

The live targets use `.venv/bin/python` and require `GEMINI_API_KEY` in `.env`.
Do not combine live-provider and offline-fixture outputs in one comparison;
`.venv/bin/python scripts/check_quality_gates.py --require-live` rejects the
latter. Record the provider/model, prompt version, immutable commit SHA,
per-case status, and any quota failures alongside the live results. The
checked-in bundle records the failed live attempt and deliberately leaves
official LLM status unavailable.
