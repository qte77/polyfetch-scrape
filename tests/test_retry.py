from polyfetch_scrape.retry import RetryPolicy, should_retry


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
