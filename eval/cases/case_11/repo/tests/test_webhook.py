from src.phoenix.webhooks import (
    send_payment_webhook,
    serialize_webhook,
    verify_webhook_signature,
)


def test_webhook_payload_serialization():
    data = serialize_webhook({"event": "ping", "id": 1})
    assert '"event": "ping"' in data


def test_webhook_signature_verification():
    assert verify_webhook_signature("sig_secret123", "secret123") is True


def test_payment_webhook():
    send_payment_webhook("https://gateway.internal/v1/payments", {"amount": 100})
