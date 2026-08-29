"""Database models for payment service."""

from pydantic import BaseModel


class PaymentMethod(BaseModel):
    id: int
    user_id: int
    provider: str
    token: str
