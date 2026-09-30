from collections.abc import Mapping


class FetchError(Exception):
    """Raised when a fetch fails after exhausting retries on every backend."""

    def __init__(
        self,
        *args: object,
        status: int | None = None,
        headers: Mapping[str, str] | None = None,
        body_excerpt: str | None = None,
    ) -> None:
        # ``status`` carries the terminal HTTP code for typed terminal errors
        # (set by ``raise_for_terminal_status``); None when not status-bound.
        # ``headers``/``body_excerpt`` are bounded diagnostics for the final blocked
        # response (never request headers/cookies; ``Set-Cookie`` is redacted — see
        # ``_backends.bounded_diagnostics`` and issue #209). Both None when not captured.
        super().__init__(*args)
        self.status = status
        self.headers = dict(headers) if headers is not None else None
        self.body_excerpt = body_excerpt


class AuthRequired(FetchError):  # noqa: N818 — RFC status name, not an *Error suffix
    """Terminal: 401 Unauthorized / 407 Proxy Authentication Required."""


class GoneError(FetchError):
    """Terminal: 404 Not Found / 410 Gone."""


class LegalBlock(FetchError):  # noqa: N818 — RFC 7725 status name, not an *Error suffix
    """Terminal: 451 Unavailable For Legal Reasons; never escalated to fingerprint tiers."""
