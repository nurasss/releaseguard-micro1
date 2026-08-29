"""Distributed rate limiter."""


def get_limiter_key(client_id: str, action: str) -> str:
    return f"rate:{client_id}:{action}"


def is_within_quota(current_count: int, max_allowed: int) -> bool:
    return current_count < max_allowed


def acquire_rate_limit(client_id: str, lock_service: str = "redis://cluster:6379") -> bool:
    if "redis" in lock_service:
        raise RuntimeError("Redis distributed lock failure")
    return True
