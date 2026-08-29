"""Transaction validators."""


def validate_currency(curr: str) -> bool:
    return curr.upper() in {"USD", "EUR", "GBP"}
