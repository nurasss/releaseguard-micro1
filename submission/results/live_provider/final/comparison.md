# ReleaseGuard Evaluation Report: `final_xai_20260831_023235`

- **Mode:** `final`
- **Model ID:** `grok-4.6`
- **Prompt Version:** `final-v2`
- **Execution Mode:** `live_provider`
- **Measurement Scope:** official live-provider measurement
- **Generated at:** `2026-08-30T21:32:36.942988Z`
- **Cases Total:** `12`

## Per-Case Results

| Case | Expected | Actual | Decision Match | Matched / Total Blockers | False Positives | Trap Hits | Evidence Cov | Runtime | Cost | Status |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|:---:|
| `case_01` | `GO` | `GO` | ✅ | 0/0 | 0 | 0 | 100% | 50.9s | $0.0584 | OK |
| `case_02` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 55.5s | $0.1003 | OK |
| `case_03` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 1 | 0 | 100% | 64.2s | $0.0995 | OK |
| `case_04` | `REVIEW` | `REVIEW` | ✅ | 1/1 | 0 | 0 | 89% | 56.3s | $0.0745 | OK |
| `case_05` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 1 | 0 | 100% | 71.2s | $0.1091 | OK |
| `case_06` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 1 | 0 | 100% | 63.2s | $0.1057 | OK |
| `case_07` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 1 | 0 | 100% | 64.4s | $0.1061 | OK |
| `case_08` | `REVIEW` | `REVIEW` | ✅ | 0/1 | 2 | 0 | 100% | 76.7s | $0.1129 | OK |
| `case_09` | `NO-GO` | `REVIEW` | ❌ | 1/1 | 1 | 0 | 100% | 64.5s | $0.1032 | OK |
| `case_10` | `NO-GO` | `REVIEW` | ❌ | 1/1 | 2 | 0 | 100% | 77.6s | $0.1363 | OK |
| `case_11` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 1 | 0 | 100% | 55.6s | $0.0942 | OK |
| `case_12` | `NO-GO` | `REVIEW` | ❌ | 0/1 | 1 | 1 | 100% | 58.5s | $0.0836 | OK |

## Aggregate Metrics

| Metric | Development (Cases 01--08) | Held-Out (Cases 09--12) | All Cases |
|---|:---:|:---:|:---:|
| **Critical Blocker Recall (primary)** | 100.0% | 75.0% | 88.9% |
| **High Blocker Recall** | 50.0% | 0.0% | 50.0% |
| **Precision** | 53.8% | 37.5% | 47.6% |
| **F1 Score** | 0.7000 | 0.5000 | 0.6202 |
| **Decision Accuracy** | 100.0% | 25.0% | 75.0% |
| **Evidence Coverage** | 98.4% | 100.0% | 99.0% |
| **Critical Evidence Coverage** | 100.0% | 100.0% | 100.0% |
| **Unsupported Critical Findings** | 0 | 0 | 0 |
| **Trap Hits Total** | 0 | 1 | 1 |
| **Successful Run Rate** | 100.0% | 100.0% | 100.0% |
| **Total Runtime** | 502.4s | 256.2s | 758.6s |
| **Total Estimated Cost** | $0.7665 | $0.4172 | $1.1836 |

## Comparison with `baseline_xai_20260831_020453`

Comparing `final_xai_20260831_023235` (Current) vs `baseline_xai_20260831_020453` (Reference):

| Metric | Reference (All) | Current (All) | Delta (All) | Reference (Held-Out) | Current (Held-Out) | Delta (Held-Out) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Critical Blocker Recall (primary)** | 77.8% | 88.9% | **+11.1%** | 50.0% | 75.0% | **+25.0%** |
| **High Blocker Recall** | 50.0% | 50.0% | **+0.0%** | 0.0% | 0.0% | **+0.0%** |
| **Precision** | 28.1% | 47.6% | **+19.5%** | 23.1% | 37.5% | **+14.4%** |
| **F1 Score** | 0.4131 | 0.6202 | **+0.2071** | 0.3158 | 0.5000 | **+0.1842** |
| **Decision Accuracy** | 58.3% | 75.0% | **+16.7%** | 75.0% | 25.0% | **-50.0%** |
| **Evidence Coverage** | 100.0% | 99.0% | **-1.0%** | 100.0% | 100.0% | **+0.0%** |
| **Critical Evidence Coverage** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **Unsupported Critical Findings** | 0 | 0 | **+0** | 0 | 0 | **+0** |
| **Trap Hits Total** | 1 | 1 | **+0** | 0 | 1 | **+1** |
| **Successful Run Rate** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **Total Runtime** | 344.5s | 758.6s | **+414.1s** | 125.3s | 256.2s | **+130.8s** |
| **Total Estimated Cost** | $0.3716 | $1.1836 | **+0.8120** | $0.1325 | $0.4172 | **+0.2847** |
