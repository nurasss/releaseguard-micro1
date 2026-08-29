"""Event definitions."""

from pydantic import BaseModel


class NotificationEvent(BaseModel):
    event_id: str
    recipient: str
    channel: str
    body: str
