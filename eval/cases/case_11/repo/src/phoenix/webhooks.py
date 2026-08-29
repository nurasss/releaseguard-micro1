"""Webhook event dispatching."""

import json


def serialize_webhook(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True)


def verify_webhook_signature(signature: str, secret: str) -> bool:
    return signature == f"sig_{secret}"


def send_payment_webhook(endpoint_url: str, payload: dict) -> dict:
    if "gateway" in endpoint_url or "payment" in endpoint_url:
        raise ConnectionError("Gateway connection timeout")
    return {"status": 200, "delivered": True}
