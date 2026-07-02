"""Internal HTTP backends.

Each backend exposes an ``attempt(...)`` callable that returns a Response on
success, raises FingerprintBlock when it suspects TLS / anti-bot is the cause
of failure (so the next backend should be tried), raises a typed terminal error
(AuthRequired / GoneError / LegalBlock) on a non-retryable terminal status, or
raises FetchError for any other terminal failure after exhausting retries.
"""

from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock


class FingerprintBlock(FetchError):  # noqa: N818 — control-flow sentinel, never surfaced to callers
    """Signal to the orchestrator that the next backend should be tried."""


# RFC 9110 / RFC 7725 terminal statuses: never retried, never escalated. Raised
# in every backend so callers get the same typed error regardless of serving tier.
_TERMINAL: dict[int, type[FetchError]] = {
    401: AuthRequired,
    407: AuthRequired,
    404: GoneError,
    410: GoneError,
    451: LegalBlock,
}


def raise_for_terminal_status(status: int, url: str) -> None:
    """Raise the mapped terminal error for a status that must not be retried or escalated."""
    exc_type = _TERMINAL.get(status)
    if exc_type is not None:
        raise exc_type(f"terminal HTTP {status}: {url}")
