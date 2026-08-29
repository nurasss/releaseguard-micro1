"""Models for settlement engine."""

from pydantic import BaseModel


class TransactionRecord(BaseModel):
    tx_id: str
    amount_cents: int
    currency: str
