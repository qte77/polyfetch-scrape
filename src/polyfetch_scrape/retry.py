from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_initial: float = 0.2
    backoff_factor: float = 2.0
    retry_on_status: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )


def should_retry(status: int, policy: RetryPolicy) -> bool:
    return status in policy.retry_on_status
