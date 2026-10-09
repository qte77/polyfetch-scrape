"""Internal HTTP backends.

Each backend exposes an ``attempt(...)`` callable that returns a Response on
success, raises FingerprintBlock when it suspects TLS / anti-bot is the cause
of failure — a 403, a TLS error, or a suspected empty-2xx soft block (#237,
see ``is_suspected_soft_block``) — so the next backend should be tried, raises
a typed terminal error (AuthRequired / GoneError / LegalBlock) on a
non-retryable terminal status, or raises FetchError for any other terminal
failure after exhausting retries.
"""

from collections.abc import Mapping

from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock


class FingerprintBlock(FetchError):  # noqa: N818 — control-flow sentinel, never surfaced to callers
    """Signal to the orchestrator that the next backend should be tried."""


# RFC 9110 §15.4.2 (301) / RFC 7538 (308): permanent moves — callers should adopt the
# new URL. Temporary redirects (302/303/307) are intentionally excluded.
_PERMANENT_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 308})


def permanent_redirect_target(status: int, headers: Mapping[str, str]) -> str | None:
    """Return the ``Location`` target for a permanent redirect (301/308), else None."""
    if status not in _PERMANENT_REDIRECT_STATUSES:
        return None
    for key, value in headers.items():
        if key.lower() == "location":
            return value
    return None


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
        raise exc_type(f"terminal HTTP {status}: {url}", status=status)


# Diagnostics attached to the final tier's blocked/exhausted response (#209) so a caller
# can tell a pure TLS/fingerprint block from a session/behavioral one without dropping to
# render_session and hand-rolling event listeners. Bounded: the body excerpt is capped, and
# Set-Cookie (a *response* header that can carry a session token) is always dropped. Never
# includes request headers/cookies — only what the blocked server sent back.
_MAX_BODY_EXCERPT_BYTES = 2048
_REDACTED_RESPONSE_HEADERS = frozenset({"set-cookie"})


def bounded_diagnostics(
    headers: Mapping[str, str] | None, body: bytes | None
) -> tuple[dict[str, str] | None, str | None]:
    """Bound a blocked/exhausted response's headers + body for exception diagnostics.

    ``headers`` is copied with ``Set-Cookie`` dropped (case-insensitively); ``None`` in stays
    ``None`` out (no response was captured, e.g. a transport-level error). ``body`` is
    truncated to ``_MAX_BODY_EXCERPT_BYTES`` and decoded as UTF-8 with a lossy fallback
    (``errors="replace"``) so a binary or non-UTF-8 blocked body never raises here.
    """
    safe_headers = (
        None
        if headers is None
        else {k: v for k, v in headers.items() if k.lower() not in _REDACTED_RESPONSE_HEADERS}
    )
    excerpt = None if not body else body[:_MAX_BODY_EXCERPT_BYTES].decode("utf-8", errors="replace")
    return safe_headers, excerpt


# A GET + 2xx + 0-byte body + HTML-or-missing Content-Type is a suspected soft block (#237):
# some anti-bot layers return an empty "success" instead of an explicit 403. Deliberately
# narrow (YAGNI): 204 (legitimately empty), HEAD/other methods, non-2xx, a non-empty body,
# and a non-HTML content type (application/json, text/plain, ...) never match.
_HTML_MEDIA_TYPE = "text/html"


def is_suspected_soft_block(
    method: str, status: int, body: bytes, content_type: str | None
) -> bool:
    """True for a GET + 2xx (not 204) + empty body + HTML-or-absent Content-Type."""
    if method.upper() != "GET":
        return False
    if status == 204 or not (200 <= status < 300):
        return False
    if body:
        return False
    if content_type is None:
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == _HTML_MEDIA_TYPE
