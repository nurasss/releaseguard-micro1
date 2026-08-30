# ReleaseGuard

ReleaseGuard is a read-only release-readiness auditor. It resolves a public
repository ref to an immutable commit, gathers bounded evidence, runs
deterministic checks, asks an Analyzer for candidate findings, verifies
critical/high findings adversarially, and applies a deterministic GO / REVIEW /
NO-GO policy.

## Security boundary

- Only public repositories are supported. A repository reported as private is
  rejected before ref resolution or content access.
- Repository data is redacted before it enters the evidence store, trajectory,
  report, or SQLite persistence boundary.
- Secret-looking files (`.env`, credentials, private keys, token/password files,
  and common certificate/key formats) have their complete contents omitted;
  only structural metadata and a content hash may remain.
- The GitHub adapter uses GET-only requests and binds content reads to the
  resolved commit SHA. Annotated tags are dereferenced to their commit.
- `.env`, local SQLite files, runtime folders, caches, and VCS metadata are
  excluded by the submission packager.

## Reproduce locally

The repository contains a frozen, self-contained 12-case fixture benchmark.
The default Make targets use `RG_OFFLINE_MODE=1` and the deterministic local
model `releaseguard-offline-v1`, so they run without a provider key and are
reproducible in CI. These scores measure the complete pipeline on the frozen
fixtures; they must not be described as a live Gemini score. A live Gemini run
can be requested with `RG_OFFLINE_MODE=0` and a valid key/quota.

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

All project commands use `.venv/bin/python`; dependencies are installed from
the exact pins in `requirements.lock`. Full reproduction details and artifact
locations are in [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Results and quality gates

`make evaluate` writes a 12-case final result and, when a baseline exists,
`comparison.json` and `comparison.md`. `make ablations` executes Verifier ON
vs OFF, evidence-enforcement and deterministic-check ablations, and the
executed It5 specialized-subagents experiment.

The quality checker evaluates CBR ≥ 0.85, absolute CBR improvement ≥ 20
percentage points, critical evidence coverage = 100%, unsupported critical
findings = 0, and successful run rate ≥ 95%:

```bash
.venv/bin/python scripts/check_quality_gates.py
```

Curated results, representative Analyzer and Verifier trajectories, the
challenging case 12 run, the removed experiment, and the comparison are
assembled under `submission/` and included in the ZIP. Uncurated local output
under `runs/`, `trajectories/`, and `eval/results/` is intentionally not
packaged.

## Development

```bash
make test
make quality-gate
docker build --tag releaseguard:local .
```

The root CI workflow runs the secret scan, frozen-data validation, tests,
offline evaluation smoke test, and Docker build.
