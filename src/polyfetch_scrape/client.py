import logging
from collections.abc import Mapping
from typing import Any, Literal

from polyfetch_scrape._backends import (
    FingerprintBlock,
    curl_backend,
    httpx_backend,
    playwright_backend,
)
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.render_options import RenderAction, RenderOptions, Screenshot
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy
from polyfetch_scrape.throttle import Throttle

__all__ = [
    "AuthRequired",
    "FetchError",
    "GoneError",
    "LegalBlock",
    "RenderAction",
    "RenderOptions",
    "Screenshot",
    "fetch",
]

Browser = Literal["chrome", "firefox"]
Tier = Literal["httpx", "curl_cffi", "playwright"]

_log = logging.getLogger(__name__)

# The playwright tier is GET-only and cannot replay a request body, so a body request
# is confined to the httpx/curl_cffi tiers (see #46).
_BODY_ON_PLAYWRIGHT_MSG = (
    "request body cannot be sent on the playwright tier (GET-only); "
    "body requests are limited to the httpx/curl_cffi tiers: {url}"
)

# Cheapest → most capable. The auto chain escalates left-to-right; min_tier/max_tier
# select a contiguous slice of this order (see #80).
_TIER_ORDER: tuple[Tier, ...] = ("httpx", "curl_cffi", "playwright")


def _tier_index(tier: Tier) -> int:
    return _TIER_ORDER.index(tier)


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    browser: Browser = "chrome",
    wait_for_selector: str | None = None,
    tier: Tier | None = None,
    min_tier: Tier | None = None,
    max_tier: Tier | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    json: Any | None = None,
    content: bytes | None = None,
    throttle: Throttle | None = None,
    render: RenderOptions | None = None,
) -> Response:
    if json is not None and content is not None:
        raise FetchError("provide either json or content, not both")
    lo, hi = _resolve_tier_range(tier, min_tier, max_tier)
    policy = retry if retry is not None else RetryPolicy()
    headers = _with_conditional_headers(headers, etag, last_modified)
    # `render` (RenderOptions) is the playwright-tier surface; `wait_for_selector` is a
    # back-compat convenience that seeds it when no explicit `render` is given.
    render = render if render is not None else RenderOptions(wait_for_selector=wait_for_selector)
    active = _TIER_ORDER[_tier_index(lo) : _tier_index(hi) + 1]
    # Proactive per-host spacing before the request (spaces distinct fetch() calls; internal
    # retries/tier-escalation within one call already honor Retry-After / backoff).
    if throttle is not None:
        throttle.acquire(url)
    return _run_chain(active, method, url, headers, timeout, policy, browser, render, json, content)


def _with_conditional_headers(
    headers: Mapping[str, str] | None,
    etag: str | None,
    last_modified: str | None,
) -> Mapping[str, str] | None:
    """Inject If-None-Match / If-Modified-Since validators for conditional GETs.

    A caller-supplied conditional header (any case) always wins over the kwarg.
    Returns ``headers`` unchanged when neither validator is requested.
    """
    if etag is None and last_modified is None:
        return headers
    merged = dict(headers) if headers is not None else {}
    present = {key.lower() for key in merged}
    if etag is not None and "if-none-match" not in present:
        merged["If-None-Match"] = etag
    if last_modified is not None and "if-modified-since" not in present:
        merged["If-Modified-Since"] = last_modified
    return merged


def _resolve_tier_range(
    tier: Tier | None, min_tier: Tier | None, max_tier: Tier | None
) -> tuple[Tier, Tier]:
    """Resolve the ``(low, high)`` tier range. ``tier=`` is sugar for a single pinned tier."""
    if tier is not None:
        if min_tier is not None or max_tier is not None:
            raise FetchError("pass either tier= or min_tier/max_tier, not both")
        return tier, tier
    lo: Tier = min_tier if min_tier is not None else "httpx"
    hi: Tier = max_tier if max_tier is not None else "playwright"
    if _tier_index(lo) > _tier_index(hi):
        raise FetchError(f"min_tier ({lo}) must not exceed max_tier ({hi})")
    return lo, hi


def _run_chain(
    active: tuple[Tier, ...],
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    browser: Browser,
    render: RenderOptions,
    json: Any | None,
    content: bytes | None,
) -> Response:
    """Walk the active tier range: escalate on FingerprintBlock; the last tier's error surfaces."""
    *escalating, final = active
    for i, current in enumerate(escalating):
        try:
            return _dispatch(
                current, method, url, headers, timeout, policy, browser, render, json, content
            )
        except FingerprintBlock:
            nxt = escalating[i + 1] if i + 1 < len(escalating) else final
            _log.info("tier escalation: %s blocked, trying %s: %s", current, nxt, url)
    return _dispatch(final, method, url, headers, timeout, policy, browser, render, json, content)


def _dispatch(
    tier: Tier,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    browser: Browser,
    render: RenderOptions,
    json: Any | None,
    content: bytes | None,
) -> Response:
    """Call one backend. Playwright is GET-only and cannot carry a request body."""
    if tier == "httpx":
        return httpx_backend.attempt(
            method, url, headers, timeout, policy, json=json, content=content
        )
    if tier == "curl_cffi":
        return curl_backend.attempt(
            method, url, headers, timeout, policy, browser=browser, json=json, content=content
        )
    if json is not None or content is not None:
        raise FetchError(_BODY_ON_PLAYWRIGHT_MSG.format(url=url))
    return playwright_backend.attempt(method, url, headers, timeout, policy, render=render)
