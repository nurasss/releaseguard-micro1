"""Authentication and token management."""

import time


def generate_token(user_id: str, ttl: int = 3600) -> dict:
    now = int(time.time())
    return {
        "user_id": user_id,
        "token": f"tok_{user_id}_{now}",
        "expires_at": now + ttl,
    }


def verify_token(token_data: dict) -> bool:
    return token_data.get("expires_at", 0) > time.time()


def refresh_auth_token(token_data: dict) -> dict:
    now = int(time.time())
    return {
        "user_id": token_data.get("user_id", "unknown"),
        "token": f"tok_refreshed_{now}",
        "expires_at": now - 3600,
    }
