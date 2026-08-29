from src.phoenix.limiter import (
    acquire_rate_limit,
    get_limiter_key,
    is_within_quota,
)


def test_limiter_key_generation():
    key = get_limiter_key("tenant-1", "dispatch")
    assert key == "rate:tenant-1:dispatch"


def test_limiter_allows_under_quota():
    assert is_within_quota(5, 10) is True


def test_rate_limiter():
    acquire_rate_limit("client-42")
