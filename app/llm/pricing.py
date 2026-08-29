# path: app/llm/pricing.py
from __future__ import annotations

from app.llm.types import Usage


# Prices per 1,000,000 prompt and output tokens in USD: {model_id: (input_price_per_1m, output_price_per_1m)}
# Default is deliberately empty: token counts are always tracked, but USD costs are only estimated when pricing is explicitly configured.
PRICES: dict[str, tuple[float, float]] = {}


def estimate_cost_usd(model_id: str, usage: Usage) -> float | None:
    """Estimate cost in USD for a given model and token usage.

    Returns None if the model is not in the PRICES table to avoid fabricating zero or arbitrary costs.
    """
    if model_id not in PRICES:
        return None

    input_price, output_price = PRICES[model_id]
    cost = (usage.prompt_tokens * input_price + usage.output_tokens * output_price) / 1_000_000.0
    return cost
