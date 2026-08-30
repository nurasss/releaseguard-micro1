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
the reproducible harness path only and are not presented as a Gemini claim.

**What failed.** The available Gemini attempt hit provider quota/rate-limit
responses before producing a successful 12-case baseline/final pair. Therefore
this bundle does not claim an official LLM improvement or official quality-gate
pass. The exact failed attempt is retained under
`submission/results/live_provider_attempt/`, and the live commands are
documented separately.

**Main failure mode.** The dangerous errors are unsupported or missed blockers:
an agent can turn a plausible signal into a critical claim, or overlook a
cross-file contradiction. Evidence IDs, deterministic checks, immutable input,
and an adversarial Verifier are designed around that failure mode.

**Hot take.** The valuable unit is a trustworthy evidence boundary, not another
agent. On these frozen, non-adversarial fixtures Verifier ON and OFF produce the
same metrics; that is a useful negative result, not proof that verification has
no value. It says the next evaluation needs contradictory evidence and
false-positive traps that can actually exercise falsification. The executed
extra-subagents experiment supports the same lesson: more orchestration is not
automatically more reliable.

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
.venv/bin/python scripts/package_submission.py
.venv/bin/python scripts/verify_submission_zip.py dist/releaseguard_submission.zip
```

All project commands use `.venv/bin/python`; dependencies are installed from
the exact pins in `requirements.lock`. Full reproduction details and artifact
locations are in [docs/REPRODUCE.md](docs/REPRODUCE.md).

## Results, provenance, and quality gates

`make evaluate` writes a 12-case final result and, when a baseline exists,
`comparison.json` and `comparison.md`. `make ablations` executes Verifier ON
vs OFF, evidence-enforcement and deterministic-check ablations, and the
executed It5 specialized-subagents experiment.

The default results have `execution_mode: offline_fixture`,
`model_id: releaseguard-offline-v1`, and `total_cost: $0.0000`. Their quality
gate output is explicitly scoped as `offline_fixture_simulation`; it is not an
official LLM baseline/final comparison. To produce an official measurement,
provision a valid Gemini key/quota and run `make baseline-live` followed by
`make evaluate-live`. The quality checker can enforce that provenance with
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
