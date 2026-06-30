from datetime import UTC, datetime

from polyfetch_scrape.retry import (
    RETRY_AFTER_CAP_S,
    RetryPolicy,
    next_delay,
    parse_retry_after,
    should_retry,
)


def test_should_retry_false_for_success() -> None:
    # Arrange
    policy = RetryPolicy()

    # Act / Assert
    assert should_retry(200, policy) is False


def test_should_retry_false_for_client_error_404() -> None:
    policy = RetryPolicy()
    assert should_retry(404, policy) is False


def test_should_retry_true_for_429() -> None:
    policy = RetryPolicy()
    assert should_retry(429, policy) is True


def test_should_retry_true_for_5xx() -> None:
    policy = RetryPolicy()
    assert should_retry(500, policy) is True
    assert should_retry(503, policy) is True


def test_should_retry_respects_custom_status_set() -> None:
    # Arrange
    policy = RetryPolicy(retry_on_status=frozenset({418}))

    # Act / Assert
    assert should_retry(418, policy) is True
    assert should_retry(503, policy) is False


def test_retry_policy_defaults() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.backoff_initial == 0.2
    assert policy.backoff_factor == 2.0
    assert 429 in policy.retry_on_status
    assert 503 in policy.retry_on_status


def test_parse_retry_after_none_returns_none() -> None:
    assert parse_retry_after(None) is None


def test_parse_retry_after_delta_seconds() -> None:
    assert parse_retry_after("120") == 120.0


def test_parse_retry_after_strips_whitespace() -> None:
    assert parse_retry_after("  5  ") == 5.0


def test_parse_retry_after_non_numeric_garbage_returns_none() -> None:
    assert parse_retry_after("soon") is None


def test_parse_retry_after_http_date_returns_seconds_until() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:30 GMT", now=now) == 30.0


def test_parse_retry_after_past_http_date_clamps_to_zero() -> None:
    now = datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC)
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:00 GMT", now=now) == 0.0


def test_parse_retry_after_naive_http_date_assumed_utc() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    # No timezone in the date -> treated as UTC rather than crashing on aware/naive math.
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:10", now=now) == 10.0


def test_next_delay_uses_retry_after_when_present() -> None:
    assert next_delay(5.0, RetryPolicy(), 0) == 5.0


def test_next_delay_caps_excessive_retry_after() -> None:
    assert next_delay(99999.0, RetryPolicy(), 0) == RETRY_AFTER_CAP_S


def test_next_delay_falls_back_to_exponential_backoff() -> None:
    policy = RetryPolicy(backoff_initial=0.2, backoff_factor=2.0)
    assert next_delay(None, policy, 0) == 0.2
    assert next_delay(None, policy, 2) == 0.8
