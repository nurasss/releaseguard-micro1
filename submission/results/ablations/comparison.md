# Ablation comparison

All rows use the same frozen 12 cases and the same offline fixture model.

| Run | CBR | Precision | Critical evidence | Unsupported critical | Successful run rate |
|---|---:|---:|---:|---:|---:|
| `final (Verifier ON)` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 |
| `no_verifier` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 |
| `no_evidence_enforcement` | 1.0000 | 1.0000 | 1.0000 | 0 | 1.0000 |
| `no_deterministic_checks` | 0.0000 | 1.0000 | 1.0000 | 0 | 1.0000 |
| `it5_subagents` | 0.5556 | 1.0000 | 1.0000 | 0 | 1.0000 |
