# Ablation comparison

All rows use the same frozen 12 cases and the same offline fixture model.

| Run | CBR | Precision | Critical evidence | Unsupported critical | Successful run rate | Runtime | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| `final (Verifier ON)` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | 782 ms | $0.0000 |
| `no_verifier` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | 729 ms | $0.0000 |
| `no_evidence_enforcement` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | 1005 ms | $0.0000 |
| `no_deterministic_checks` | 0.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | 412 ms | $0.0000 |
| `no_tool_output_normalization` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 | 840 ms | $0.0000 |
| `it5_subagents` | 0.5556 | 1.0000 | 1.0000 | 0 | 1.0000 | 782 ms | $0.0000 |

## Interpretation

- Verifier ON and `no_verifier` have the same metrics on these frozen, non-adversarial cases; this does not support a metric-lift claim for verification.
- Evidence enforcement ON/OFF also matches because no unsupported critical candidate was emitted in this run.
- `no_deterministic_checks` and It5 show the meaningful negative controls: removing deterministic evidence or adding specialized agents reduced quality.
