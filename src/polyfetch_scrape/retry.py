from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

RETRY_AFTER_CAP_S: float = 60.0


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


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds.

    Returns ``None`` when the header is absent or unparseable, so callers fall
    back to exponential backoff.
    """
    if value is None:
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    current = now if now is not None else datetime.now(UTC)
    return max(0.0, (when - current).total_seconds())


def next_delay(retry_after: float | None, policy: RetryPolicy, attempt_idx: int) -> float:
    """Seconds to wait before the next attempt.

    A server-provided ``Retry-After`` (capped at ``RETRY_AFTER_CAP_S`` to avoid a
    pathological hang) wins; otherwise exponential backoff.
    """
    if retry_after is not None:
        return min(retry_after, RETRY_AFTER_CAP_S)
    return policy.backoff_initial * (policy.backoff_factor**attempt_idx)
