# Evaluation result provenance

The baseline, final, and ablation directories in this bundle are the reproducible `releaseguard-offline-v1` fixture simulation. Their numeric quality gates are not official LLM benchmark results. The official live measurement status is recorded in `official_llm_status.json`; the failed provider attempt is retained under `live_provider_attempt/`.

To create an official comparison with a valid Gemini key and quota, run `make baseline-live`, `make evaluate-live`, and then use `scripts/check_quality_gates.py --require-live`.
