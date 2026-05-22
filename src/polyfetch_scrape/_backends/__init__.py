"""Internal HTTP backends.

Each backend exposes an ``attempt(...)`` callable that returns a Response on
success, raises FingerprintBlock when it suspects TLS / anti-bot is the cause
of failure (so the next backend should be tried), or raises FetchError for any
other terminal failure after exhausting retries.
"""

from polyfetch_scrape.errors import FetchError


class FingerprintBlock(FetchError):  # noqa: N818 — control-flow sentinel, never surfaced to callers
    """Signal to the orchestrator that the next backend should be tried."""
