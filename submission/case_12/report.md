# ReleaseGuard Audit

Repository: https://github.com/eval/case_12
Requested ref: v4.0.0
Commit: fc00d35fc5c809b82e27fcd01df6e714c3efa9a1
Decision: NO-GO

## Executive summary

Analyzed 1 candidate finding(s) across 10 deterministic check(s). Decision: NO-GO. 1 confirmed critical, 0 confirmed high, 0 finding(s) require human review, 0 rejected.

## Confirmed blockers

### F-001 — CRITICAL
Integration tests are not run by the configured CI test command; the integration path is untested.

Evidence:
E-001 — test_report — Test report: 4/4 passed, 0 failed

Verification: CONFIRMED
Confidence: 0.99

Recommended action:
Resolve the observed release-readiness gap and rerun the audit.


## High-risk warnings

None.

## Uncertain findings (needs human review)

None.

## Deterministic checks

Passed:
- DC-02 CI workflow presence: Found 1 workflow file(s): ['.github/workflows/ci.yml'].
- DC-03 CI release-ref trigger configuration: Workflow(s) ['.github/workflows/ci.yml'] are configured to trigger for ref 'v4.0.0'.
- DC-04 Latest CI run status for release ref: Latest recorded CI run for ref 'v4.0.0' has conclusion=success.
- DC-05 Release version metadata consistency: Manifest pyproject.toml version '4.0.0' matches requested ref 'v4.0.0'.
- DC-10 Secret scan: No known secret patterns detected across 11 scanned text file(s).

Other results:
- DC-01 Test configuration and execution [warn]: Repository contains 6 test function(s) across 2 test file(s) (['tests/test_payment_gateway_integration.py', 'tests/test_unit.py']), but the latest test report only accounts for 4 test(s). Some tests may be excluded from execution (e.g. by a marker filter).
- DC-06 Lockfile presence [warn]: A dependency manifest is present but no recognized lockfile was found; reproducible installs are not guaranteed.
- DC-07 Build/release command [not_applicable]: No build/release command declared (no matching pyproject.toml [project.scripts], package.json scripts, or Makefile 'build' target) and no build report available.
- DC-08 Required environment variable documentation [not_applicable]: No required (default-less) environment variable access detected in source.
- DC-09 Migration execution coverage [not_applicable]: No migration directory or migration files found in repository.

## Other findings

None.

## Findings rejected by Verifier

None.

## Recommended human actions

- F-001: Resolve the observed release-readiness gap and rerun the audit.

## Limitations

- Model releaseguard-offline-v1 pricing is not configured; cost is tracked via tokens (153 total tokens)

## Run metadata

Runtime: 66 ms
Model: releaseguard-offline-v1
Prompt version: p1
Estimated LLM cost: $0.0000
