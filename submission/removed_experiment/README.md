# Removed experiment: It5 specialized subagents

This is the executed comparison requested by the changelog. It runs CI,
security, and test specialists and combines their bounded outputs before
the same verifier and decision policy. The measured result is stored under
`results/ablations/it5_subagents/`.

All-case CBR: 0.5556
All-case precision: 1.0
All-case decision accuracy: 0.5833
Critical evidence coverage: 1.0
Unsupported critical findings: 0
All-case successful run rate: 1.0
Runtime: 782 ms
Cost: $0.0000
Decision: REMOVE — the extra specialists reduced CBR on the frozen cases.
