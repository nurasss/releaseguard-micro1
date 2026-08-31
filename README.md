# ReleaseGuard

ReleaseGuard is a read-only release-readiness auditor. It resolves a public
repository ref to an immutable commit, gathers bounded evidence, runs
deterministic checks, asks an Analyzer for candidate findings, verifies
critical/high findings adversarially, and applies a deterministic GO / REVIEW /
NO-GO policy.

## User story and value

**Persona.** A Tech Lead, Release Engineer, or senior developer on a small or
medium product team without a dedicated release-QA function.

**Bottleneck.** Release evidence is split across CI status, tests, build
scripts, manifests, lockfiles, version metadata, environment declarations,
migrations, workflows, and documentation. A manual review can miss a blocker,
overweight a weak signal, or leave no auditable trail for the decision.

**Value.** Given a public repository and ref, ReleaseGuard binds the audit to
an immutable SHA and produces a redacted, evidence-backed GO / REVIEW / NO-GO
report in minutes. It reduces evidence collection and first-pass reasoning; a
qualified human still owns the release decision.

**The baseline story.** The official B1 definition is one general-purpose LLM
agent with the same snapshot, read-only tools, cases, and output contract as
the final system, but without the explicit checklist, evidence contract, or
Analyzer -> Verifier separation. The checked-in 12-case run is an
`OfflineFixtureLLM` simulation of that control, not an official LLM result. It
scored CBR `0.4444` and decision accuracy `0.4167`; the simulated final path
scored CBR `1.0000` and decision accuracy `1.0000`. These numbers demonstrate
the reproducible harness path only and are not presented as a live-provider claim.

**What failed.** The original Gemini attempt hit provider quota/rate-limit
responses. A later xAI `grok-4.6` pair completed all 12 baseline and final cases,
but the official improvement gate failed: CBR moved from `0.7778` to `0.8889`
(`+11.11` percentage points, below the required `+20`). The bundle preserves
both the successful live pair and the failed gate without substituting fixture
metrics.

**Case 12 evaluation breakdown.** In the flagship held-out case (`case_12`),
the model correctly discovered the exact root cause: *"CI runs pytest -v -m 'not integration',
which excludes the two @pytest.mark.integration tests in tests/test_payment_gateway_integration.py"*.
The case still scored as a miss. Two of the three causes are measurement
artifacts and the third is a real model shortcoming:
1. *Exact token mismatch (artifact, caused the CBR miss):* The frozen gold matcher
   required the specific token `excluded` (e.g. `["integration", "tests", "excluded"]`),
   but the model emitted the active verb `excludes`. All 11 frozen keyword sets
   failed on that single word-form; each was otherwise one token from matching.
2. *False trap hit (artifact):* The finding mentioned *"accounts for only 4 passed tests"*
   alongside *"integration"*, which accidentally satisfied the forbidden trap set
   `["integration", "tests", "passed"]` — a set meant to catch the opposite claim,
   that integration tests ran successfully.
3. *Severity calibration (a real miss, not an artifact):* The finding was graded
   `HIGH` rather than `CRITICAL`, which produced `REVIEW` instead of the expected
   `NO-GO`. This did not cause the CBR miss — the matcher accepts `high` for a
   critical gold blocker — but it is a genuine calibration failure that the It9
   severity contract did not close on held-out data.
Rather than retroactively altering the frozen gold matcher (which would violate
evaluation protocol §10/§21), this failure is preserved and reported as an honest
insight into the brittleness of keyword-based benchmark evaluation.

**Main failure mode.** The dangerous errors are unsupported or missed blockers:
an agent can turn a plausible signal into a critical claim, or overlook a
cross-file contradiction. Evidence IDs, deterministic checks, immutable input,
and an adversarial Verifier are designed around that failure mode.

**Hot take.** The valuable unit is a trustworthy evidence boundary, not another
agent. Two independent measurements say the same thing. On the frozen offline
fixtures Verifier ON and OFF produce identical metrics. In the live xAI final
run the Verifier confirmed all `21` critical/high candidates and rejected `0`,
so its measured contribution to precision on this data is zero. That is a
useful negative result, not proof that verification has no value: it says the
evaluation needs contradictory evidence and false-positive traps that can
actually exercise falsification.

Where the live precision gain actually came from is measurable and is not the
Verifier. B1 emitted `32` critical/high findings across the 12 cases and the
final system emitted `21`; precision moved from `0.2812` to `0.4762` (held-out
`0.2308` to `0.3750`) because the severity contract introduced in It9 stopped
the Analyzer from grading weak signals as blockers, not because anything was
rejected downstream. Attributing that delta to the Verifier would credit the
component that provably did nothing here. The removed It5 extra-subagents
experiment carries the same lesson from the other direction: more orchestration
is not automatically more reliable, and it degraded CBR to `0.5556`.

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
fixtures; they must not be described as a live LLM score. The current live-run
profile uses xAI `grok-4.6`; Google Gemini remains supported as an alternative.

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

All project commands use `.venv/bin/python`; dependencies are installed from
the exact pins in `requirements.lock`. Full reproduction details and artifact
locations are in [docs/REPRODUCE.md](docs/REPRODUCE.md).

### CLI usage (§32)

```bash
# Direct CLI binary:
.venv/bin/releaseguard audit --repo https://github.com/owner/repo --ref v1.0.0 --mode final
.venv/bin/releaseguard audit --case eval/cases/case_12 --mode final

# Or via Python module:
.venv/bin/python -m app.cli audit --case eval/cases/case_12 --mode final
```


## Results, provenance, and quality gates

`make evaluate` writes a 12-case final result and, when a baseline exists,
`comparison.json` and `comparison.md`. `make ablations` executes Verifier ON
vs OFF, evidence-enforcement and deterministic-check ablations, and the
executed It5 specialized-subagents experiment.

The reproducible fixture results have `execution_mode: offline_fixture`,
`model_id: releaseguard-offline-v1`, and `total_cost: $0.0000`. Their quality
gate output is explicitly scoped as `offline_fixture_simulation`; it is not an
official LLM baseline/final comparison. The included live xAI measurement is
official-provider eligible but fails the improvement gate. To rerun it,
provision a fresh xAI key as `XAI_API_KEY` and run `make baseline-live` followed
by `make evaluate-live`. Both targets default to xAI `grok-4.6`; override them
with `LIVE_PROVIDER=google LIVE_MODEL=gemini-2.5-flash` if needed. The quality
checker enforces matching execution mode, provider, and model with
`--require-live`.

The target gates are CBR ≥ 0.85, absolute improvement ≥ 20 percentage points,
critical evidence coverage = 100%, unsupported critical findings = 0, and
successful run rate ≥ 95%:

```bash
.venv/bin/python scripts/check_quality_gates.py
# Official-only check (expected to fail for the checked-in fixture artifacts):
.venv/bin/python scripts/check_quality_gates.py --require-live
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

## Submission map

- `docs/IMPROVEMENT_CHANGELOG.md` records each executed experiment, including
  the removed It5 subagent experiment and the Verifier negative result.
- `docs/REPRODUCE.md` gives clean-environment commands, versions, runtime, and
  cost boundaries.
- `submission/` contains the selected 12-case simulation artifacts, comparison,
  ablations, case 12 report, Analyzer/Verifier trajectories, live-provider
  status, and the video. The archive verifier checks the extracted ZIP.
