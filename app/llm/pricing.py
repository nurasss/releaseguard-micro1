# path: app/llm/pricing.py
from __future__ import annotations

from app.llm.types import Usage


# Prices per 1,000,000 prompt and output tokens in USD: {model_id: (input_price_per_1m, output_price_per_1m)}
# Unlisted models deliberately have no entry: token counts are always tracked, but USD costs
# are only estimated when pricing is explicitly configured — a missing entry must never be
# silently reported as a $0.00 cost.
#
# gemini-2.5-flash: publicly documented standard-tier rate ($0.30 / 1M input tokens,
# $2.50 / 1M output tokens) as of the frozen_at date in eval/EVALUATION_SPEC.md. This is an
# approximation for reporting purposes, not a vendor-guaranteed billing figure — Google's
# pricing page is the source of truth and may have changed since.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    # xAI public text-token pricing documented for Grok 4.6 as of 2026-08-31.
    "grok-4.6": (2.00, 6.00),
}


def estimate_cost_usd(model_id: str, usage: Usage) -> float | None:
    """Estimate cost in USD for a given model and token usage.

    Returns None if the model is not in the PRICES table to avoid fabricating zero or arbitrary costs.
    """
    if model_id not in PRICES:
        return None

    input_price, output_price = PRICES[model_id]
    cost = (usage.prompt_tokens * input_price + usage.output_tokens * output_price) / 1_000_000.0
    return cost
