class FetchError(Exception):
    """Raised when a fetch fails after exhausting retries on every backend."""


class AuthRequired(FetchError):  # noqa: N818 — RFC status name, not an *Error suffix
    """Terminal: 401 Unauthorized / 407 Proxy Authentication Required."""


class GoneError(FetchError):
    """Terminal: 404 Not Found / 410 Gone."""


class LegalBlock(FetchError):  # noqa: N818 — RFC 7725 status name, not an *Error suffix
    """Terminal: 451 Unavailable For Legal Reasons; never escalated to fingerprint tiers."""
