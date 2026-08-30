# Improvement changelog

## 2026-08-30 — submission hardening

- Replaced the unfinished final-mode branch with the complete pipeline:
  deterministic checks → Analyzer → Verifier → decision policy → report.
- Added schema-constrained Analyzer planning and findings, bounded tool calls,
  evidence-id validation, and a single-finding adversarial Verifier.
- Added redaction at the evidence persistence boundary. Sensitive file bodies
  are omitted before report or SQLite serialization; trajectory inputs and
  summaries are redacted and bounded as well.
- Added a public-repository guard and read-only GitHub source behavior. Branches,
  lightweight tags, annotated tags, releases, and commit refs resolve to an
  immutable commit SHA.
- Added `SnapshotManager`, which writes a content-free `snapshot.json` with the
  resolved SHA and tree digest for every successful audit.
- Pinned runtime and development dependencies in `requirements.lock`; all Make
  targets use `.venv/bin/python` after the one-time venv bootstrap.
- Added deterministic offline fixture execution, 12-case evaluation output,
  baseline/final comparison, ablations, automatic quality-gate reporting, and
  ZIP extraction verification.
- Added README, reproducibility instructions, a root CI workflow, Docker lock
  installation, secret scanning, and curated submission artifact generation.

## Executed experiments

The submission run executes the following on the same frozen 12 cases:

1. Baseline (`releaseguard-offline-v1`, direct report signals only).
2. Final (`releaseguard-offline-v1`, deterministic checks + Analyzer + Verifier).
3. Verifier ON vs OFF (`no_verifier`).
4. Evidence enforcement and deterministic-check ablations.
5. It5 specialized CI / Security / Test subagents, retained as the **removed
   experiment** because it adds orchestration cost without replacing the
   single Analyzer path.

The offline fixture model is deliberately labelled in every result. An earlier
live Gemini attempt was recorded as unsuccessful because the configured
provider returned quota/rate-limit errors; it is not mixed into the offline
quality-gate denominator. This keeps the comparison honest and reproducible.

## Remaining interpretation boundary

The frozen local benchmark proves the implementation path and its deterministic
quality gates. It does not substitute for an independently provisioned live
Gemini measurement. A live-provider score must be generated separately with a
valid key/quota and must preserve the model ID, prompt version, commit SHA, and
raw per-case status in its own results directory.
