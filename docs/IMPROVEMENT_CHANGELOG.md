# Improvement changelog

## How to read this changelog

The frozen scorer and 12-case set were held constant. The checked-in results
below are explicitly **offline fixture simulations** because the available
Gemini quota did not produce a successful live-provider pair. They are useful
for testing the pipeline and its evidence invariants, but they are not official
LLM baseline/final scores. Runtime is aggregate wall-clock time; fixture cost
is `$0.0000` because no provider call is made.

## Stage B1 - General-purpose baseline

- **Observed failure:** direct report signals missed most release blockers and
  did not consistently distinguish the expected decisions.
- **Hypothesis:** a reasonable single-agent starting point establishes a fair
  control for the same snapshot, tools, cases, and output contract.
- **Change:** use `OfflineFixtureLLM` in B1 mode to emulate direct findings from
  the available deterministic report signals; no explicit release checklist,
  evidence-enforcement contract, or Verifier routing.
- **Evaluation run:** `baseline_20260830_220320`, all 12 frozen cases.
- **Metric before:** not applicable (starting point).
- **Metric after:** CBR `0.4444`; decision accuracy `0.4167`; precision `1.0000`;
  critical evidence coverage `1.0000`; unsupported critical `0`; successful
  run rate `1.0000`; runtime `399 ms`; cost `$0.0000`.
- **Decision:** **KEEP** as the baseline control, but label it simulation until
  a live B1 run is available.
- **Learning:** a direct signal-to-report path is a weak release-readiness
  control even when its emitted findings are evidence-backed.

## Stage It1 - Structured release checklist and deterministic evidence

- **Observed failure:** B1 could not systematically cover CI, tests, build,
  environment, version, migration, and workflow signals.
- **Hypothesis:** deterministic checks plus an explicit AuditPlan should improve
  missed-blocker recall without asking the LLM to rediscover parser rules.
- **Change:** route the final path through the ten DC checks, an Analyzer plan,
  bounded read-only tools, and evidence IDs tied to the immutable SHA.
- **Evaluation run:** `final_20260830_220325`, all 12 frozen cases.
- **Metric before:** B1 CBR `0.4444`, decision accuracy `0.4167`.
- **Metric after:** CBR `1.0000`; decision accuracy `1.0000`; precision
  `1.0000`; critical evidence coverage `1.0000`; unsupported critical `0`;
  successful run rate `1.0000`; runtime `782 ms`; cost `$0.0000`.
- **Decision:** **KEEP**.
- **Learning:** on this fixture set, deterministic coverage and structured
  evidence account for the observable gain in the simulation.

## Stage It2 - Evidence contract and persistence redaction

- **Observed failure:** a correct finding is still unsafe if its evidence or a
  secret-file body leaks into a report, trajectory, or database.
- **Hypothesis:** redaction before persistence and strict evidence-ID
  validation can preserve auditability without exposing secret contents.
- **Change:** redact payloads before EvidenceStore/SQLite/report persistence;
  omit secret-looking file bodies; validate current-run immutable-SHA evidence;
  reject private repositories before content access.
- **Evaluation run:** security regression suite plus the same final pipeline;
  `make test` (302 tests) and `final_20260830_220325`.
- **Metric before:** no safe persistence gate; one repository security test
  failure exposed literal synthetic AWS-like examples in tracked test code.
- **Metric after:** `302 passed`; critical evidence coverage `1.0000`; unsupported
  critical `0`; ZIP secret/runtime verifier PASS.
- **Runtime/cost impact:** no measurable provider/runtime cost; fixture cost
  `$0.0000`.
- **Decision:** **KEEP**.
- **Learning:** the redaction boundary must be enforced by the storage layer,
  not only by a standalone scan or a caller convention.

## Stage It3 - Analyzer -> Verifier falsification

- **Observed failure:** generation can turn a plausible signal into an
  overconfident high/critical claim.
- **Hypothesis:** an independent Verifier that searches for contradicting
  evidence should reduce unsupported or false-positive blockers.
- **Change:** send every critical/high candidate to a structured Verifier that
  attempts falsification and can return `confirmed`, `rejected`, or `uncertain`.
- **Evaluation run:** final `final_20260830_220325` versus
  `ablation_no_verifier_20260830_220331`.
- **Metric before:** Verifier OFF CBR `1.0000`; precision `1.0000`; critical
  evidence coverage `1.0000`; unsupported critical `0`; runtime `729 ms`.
- **Metric after:** Verifier ON CBR `1.0000`; precision `1.0000`; critical
  evidence coverage `1.0000`; unsupported critical `0`; runtime `782 ms`;
  cost `$0.0000`.
- **Decision:** **KEEP, REVISE evaluation**.
- **Learning:** there is no measured metric lift on these non-adversarial
  fixtures. Verification remains a safety guardrail, but future cases must
  contain contradictory evidence and false-positive traps to test its stated
  contribution.

## Stage It4 - Evidence-enforcement ablation

- **Observed failure:** without an explicit persistence/contract boundary, a
  future model could emit a blocker without resolvable evidence.
- **Hypothesis:** enforcement should preserve critical evidence coverage and
  prevent unsupported critical findings.
- **Change:** compare the final path with `no_evidence_enforcement` while
  keeping the same cases and scorer.
- **Evaluation run:** `ablation_no_evidence_enforcement_20260830_220331`.
- **Metric before:** enforcement ON CBR `1.0000`; critical evidence coverage
  `1.0000`; unsupported critical `0`.
- **Metric after:** ablation CBR `1.0000`; critical evidence coverage `1.0000`;
  unsupported critical `0`; precision `1.0000`; runtime `1005 ms`.
- **Decision:** **KEEP, REVISE evaluation**.
- **Learning:** the frozen cases emitted no unsupported critical candidates, so
  this ablation cannot demonstrate a difference yet; the invariant still
  protects the production boundary.

## Stage It5 - Three additional specialized subagents (removed)

- **Observed failure:** before running it, the open question was whether CI,
  Security, and Test specialists would improve recall enough to justify extra
  orchestration.
- **Hypothesis:** specialization improves coverage over the single Analyzer.
- **Change:** execute CI, Security, and Test subagents sequentially, combine
  their bounded findings, then use the same Verifier and decision policy.
- **Evaluation run:** `ablation_it5_subagents_20260830_220331`, all 12 cases.
- **Metric before:** final CBR `1.0000`; decision accuracy `1.0000`; runtime
  `782 ms`.
- **Metric after:** CBR `0.5556`; high-blocker recall `0.5000`; decision accuracy
  `0.5833`; precision `1.0000`; critical evidence coverage `1.0000`; unsupported
  critical `0`; runtime `782 ms`; cost `$0.0000`.
- **Decision:** **REMOVE** from the default route; retain the raw ablation as
  evidence.
- **Learning:** more agents did not improve this task and materially reduced
  recall/decision quality in this run. Specialization must earn its place on
  the frozen scorer.

## Stage It6 - Tool-output normalization and deterministic-check removal

- **Observed failure:** large raw tool outputs can obscure the signal, while
  removing deterministic checks removes the most reliable coverage source.
- **Hypothesis:** normalized summaries should preserve context; removing checks
  should expose their contribution.
- **Change:** keep parser/normalizer -> structured Evidence -> agent context as
  the default and run the explicit `no_deterministic_checks` ablation.
- **Evaluation run:** `ablation_no_deterministic_checks_20260830_220331`.
- **Metric before:** final CBR `1.0000`; decision accuracy `1.0000`.
- **Metric after:** CBR `0.0000`; high-blocker recall `0.5000`; decision accuracy
  `0.1667`; precision `1.0000`; critical evidence coverage `1.0000`; unsupported
  critical `0`; runtime `412 ms`.
- **Decision:** **KEEP** normalization and deterministic checks.
- **Learning:** lower runtime is not a win when it removes the evidence needed
  to detect blockers.

The paired `no_tool_output_normalization` run
`ablation_no_tool_output_normalization_20260830_220331` exercised the wired
serialized-payload path. It produced CBR `1.0000`, decision accuracy `1.0000`,
critical evidence coverage `1.0000`, unsupported critical `0`, successful run
rate `1.0000`, runtime `840 ms`, and cost `$0.0000`. **KEEP** the normalized
default; the ablation shows no difference on the fixture model, so this result
does not justify a quality claim about context normalization.

## Stage It7 - Live-provider reproducibility attempt

- **Observed failure:** the configured Gemini provider returned quota/rate-limit
  errors (HTTP 429) before a successful 12-case run.
- **Hypothesis:** an official LLM baseline/final pair would let the benchmark
  claim the hackathon improvement gate.
- **Change:** run the provider path with the frozen model ID and retain the
  failure artifact instead of replacing it with fixture numbers.
- **Evaluation run:** `baseline_official_run` in
  `submission/results/live_provider_attempt/results.json`.
- **Metric before:** no official measurement.
- **Metric after:** successful run rate `0.0000` for that failed baseline
  attempt; total runtime `2,106.1 s`; estimated cost `$0.0024`; no official
  final comparison was produced.
- **Decision:** **REVISE** by rerunning only with a valid quota; do not claim
  official quality gates from the fixture simulation.
- **Learning:** provenance is part of the result. A mathematically attractive
  offline score cannot stand in for the requested LLM experiment.

## Summary decision

The final implementation keeps deterministic evidence, structured Analyzer /
Verifier contracts, redaction, and read-only public-repository guards. It
removes It5 from the default route. The checked-in numeric gates pass only for
the reproducible offline fixture scope; official live LLM gates remain
unavailable and are explicitly marked as such.
