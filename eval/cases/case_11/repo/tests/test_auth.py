import time
from src.phoenix.auth import generate_token, refresh_auth_token, verify_token


def test_generate_token():
    tok = generate_token("user-1")
    assert tok["user_id"] == "user-1"
    assert tok["expires_at"] > time.time()


def test_verify_valid_token():
    tok = generate_token("user-2", ttl=60)
    assert verify_token(tok) is True


def test_auth_token_refresh():
    tok = generate_token("user-3", ttl=60)
    refreshed = refresh_auth_token(tok)
    assert verify_token(refreshed) is True, "Token expired during dispatch"
