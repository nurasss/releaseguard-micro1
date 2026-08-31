# Reproduce ReleaseGuard

## Prerequisites

- Python 3.11 or newer (for host execution)
- Docker & Docker Compose (for containerized reproduction)
- A checkout of this repository at the submission commit

The fixture evaluation does not require external LLM or GitHub credentials.

## Frozen versions and provenance

- Project requirement: Python `>=3.11` (`pyproject.toml`); the reference run
  used the repository `.venv` interpreter.
- Dependency versions: every runtime and development pin is recorded with
  `==` in `requirements.lock`; `make setup` installs that file first.
- Current live rerun profile: xAI `grok-4.6`; fixture model ID:
  `releaseguard-offline-v1`. The earlier Gemini attempt remains preserved as a
  failed provider attempt, not as benchmark data.
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
`$0.0000`: it makes no provider calls. A live reproduction has no fixed cost;
cost depends on token usage and current provider pricing, and the run records
`estimated_cost` per case.

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

Revoke any key that has appeared in chat or logs. Put a fresh xAI key only in
the ignored local `.env` file:

```dotenv
XAI_API_KEY=your-new-key
```

Then run the matched baseline/final pair:

```bash
make baseline-live
make evaluate-live
```

The live targets use `.venv/bin/python` and default to
`LIVE_PROVIDER=xai LIVE_MODEL=grok-4.6 LIVE_PROMPT_VERSION=final-v2`. Google remains available with
`make baseline-live evaluate-live LIVE_PROVIDER=google LIVE_MODEL=gemini-2.5-flash`
and `GEMINI_API_KEY`.
Do not combine live-provider and offline-fixture outputs in one comparison;
`.venv/bin/python scripts/check_quality_gates.py --require-live` rejects the
latter and also rejects mismatched providers or models. Record the
provider/model, prompt version, immutable commit SHA,
per-case status, and any quota failures alongside the live results. The
checked-in bundle records both the earlier failed attempt and the completed xAI
pair. The pair is official-provider eligible, but its improvement gate is FAIL
(`+11.11` percentage points versus the required `+20`).

## Docker and clean container reproduction (§36)

ReleaseGuard can be built, audited, and served entirely in an isolated Docker
container with zero host dependencies beyond Docker.

### 1. Build and run the API service via Compose

```bash
# Copy template env if not already present
cp .env.example .env

# Build image and start API server
docker compose up --build -d

# Verify service health and readiness
curl http://localhost:8000/health
curl http://localhost:8000/ready

# Stop the container
docker compose down
```

### 2. Standalone container audit CLI

```bash
# Build standalone image
docker build -t releaseguard:local .

# Run deterministic audit inside container with mounted output directory
docker run --rm \
  -e RG_OFFLINE_MODE=1 \
  -v $(pwd)/runs:/app/runs \
  -v $(pwd)/trajectories:/app/trajectories \
  releaseguard:local releaseguard audit --case eval/cases/case_12 --mode final

# Or run live audit inside container (passing API key)
docker run --rm \
  --env-file .env \
  -v $(pwd)/runs:/app/runs \
  -v $(pwd)/trajectories:/app/trajectories \
  releaseguard:local releaseguard audit --repo https://github.com/owner/repo --ref main --mode final
```

