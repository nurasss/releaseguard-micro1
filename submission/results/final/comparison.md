# ReleaseGuard Evaluation Report: `final_20260830_213022`

- **Mode:** `final`
- **Model ID:** `releaseguard-offline-v1`
- **Prompt Version:** `offline-final-v1`
- **Generated at:** `2026-08-30T16:30:23.607523Z`
- **Cases Total:** `12`

## Per-Case Results

| Case | Expected | Actual | Decision Match | Matched / Total Blockers | False Positives | Trap Hits | Evidence Cov | Runtime | Cost | Status |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|:---:|
| `case_01` | `GO` | `GO` | ✅ | 0/0 | 0 | 0 | 0% | 0.0s | $0.0000 | OK |
| `case_02` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.0s | $0.0000 | OK |
| `case_03` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.0s | $0.0000 | OK |
| `case_04` | `REVIEW` | `REVIEW` | ✅ | 1/1 | 0 | 0 | 100% | 0.0s | $0.0000 | OK |
| `case_05` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_06` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_07` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_08` | `REVIEW` | `REVIEW` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_09` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_10` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_11` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |
| `case_12` | `NO-GO` | `NO-GO` | ✅ | 1/1 | 0 | 0 | 100% | 0.1s | $0.0000 | OK |

## Aggregate Metrics

| Metric | Development (Cases 01--08) | Held-Out (Cases 09--12) | All Cases |
|---|:---:|:---:|:---:|
| **Critical Blocker Recall (primary)** | 100.0% | 100.0% | 100.0% |
| **High Blocker Recall** | 100.0% | 0.0% | 100.0% |
| **Precision** | 100.0% | 100.0% | 100.0% |
| **F1 Score** | 1.0000 | 1.0000 | 1.0000 |
| **Decision Accuracy** | 100.0% | 100.0% | 100.0% |
| **Evidence Coverage** | 100.0% | 100.0% | 100.0% |
| **Critical Evidence Coverage** | 100.0% | 100.0% | 100.0% |
| **Unsupported Critical Findings** | 0 | 0 | 0 |
| **Trap Hits Total** | 0 | 0 | 0 |
| **Successful Run Rate** | 100.0% | 100.0% | 100.0% |
| **Total Runtime** | 0.4s | 0.3s | 0.7s |
| **Total Estimated Cost** | $0.0000 | $0.0000 | $0.0000 |

## Comparison with `baseline_20260830_213016`

Comparing `final_20260830_213022` (Current) vs `baseline_20260830_213016` (Reference):

| Metric | Reference (All) | Current (All) | Delta (All) | Reference (Held-Out) | Current (Held-Out) | Delta (Held-Out) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Critical Blocker Recall (primary)** | 44.4% | 100.0% | **+55.6%** | 25.0% | 100.0% | **+75.0%** |
| **High Blocker Recall** | 0.0% | 100.0% | **+100.0%** | 0.0% | 0.0% | **+0.0%** |
| **Precision** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **F1 Score** | 0.6154 | 1.0000 | **+0.3846** | 0.4000 | 1.0000 | **+0.6000** |
| **Decision Accuracy** | 41.7% | 100.0% | **+58.3%** | 25.0% | 100.0% | **+75.0%** |
| **Evidence Coverage** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **Critical Evidence Coverage** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **Unsupported Critical Findings** | 0 | 0 | **+0** | 0 | 0 | **+0** |
| **Trap Hits Total** | 0 | 0 | **+0** | 0 | 0 | **+0** |
| **Successful Run Rate** | 100.0% | 100.0% | **+0.0%** | 100.0% | 100.0% | **+0.0%** |
| **Total Runtime** | 0.4s | 0.7s | **+0.3s** | 0.1s | 0.3s | **+0.1s** |
| **Total Estimated Cost** | $0.0000 | $0.0000 | **+0.0000** | $0.0000 | $0.0000 | **+0.0000** |
