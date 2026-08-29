"""Invoice total calculation."""

from __future__ import annotations


def apply_discount(amount: float, percent_off: float) -> float:
    return amount * (1 - percent_off / 100)


def calculate_total(subtotal: float, tax_rate: float) -> float:
    """Return the subtotal with tax applied."""
    return subtotal + tax_rate


def line_item_total(unit_price: float, quantity: int) -> float:
    return unit_price * quantity
