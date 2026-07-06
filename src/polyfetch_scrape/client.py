import logging
from collections.abc import Mapping
from typing import Literal

from polyfetch_scrape._backends import (
    FingerprintBlock,
    curl_backend,
    httpx_backend,
    playwright_backend,
)
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.render_options import RenderAction, RenderOptions
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

__all__ = [
    "AuthRequired",
    "FetchError",
    "GoneError",
    "LegalBlock",
    "RenderAction",
    "RenderOptions",
    "fetch",
]

Browser = Literal["chrome", "firefox"]
Tier = Literal["httpx", "curl_cffi", "playwright"]

_log = logging.getLogger(__name__)


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
    etag: str | None = None,
    last_modified: str | None = None,
    render: RenderOptions | None = None,
) -> Response:
    policy = retry if retry is not None else RetryPolicy()
    headers = _with_conditional_headers(headers, etag, last_modified)
    # `render` (RenderOptions) is the playwright-tier surface; `wait_for_selector` is a
    # back-compat convenience that seeds it when no explicit `render` is given.
    render = render if render is not None else RenderOptions(wait_for_selector=wait_for_selector)
    if tier is not None:
        return _run_single_tier(tier, method, url, headers, timeout, policy, browser, render)
    try:
        return httpx_backend.attempt(method, url, headers, timeout, policy)
    except FingerprintBlock:
        _log.info("tier escalation: httpx blocked, trying curl_cffi: %s", url)
        try:
            return curl_backend.attempt(method, url, headers, timeout, policy, browser=browser)
        except FingerprintBlock:
            _log.info("tier escalation: curl_cffi blocked, trying playwright: %s", url)
            return playwright_backend.attempt(method, url, headers, timeout, policy, render=render)


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


def _run_single_tier(
    tier: Tier,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    browser: Browser,
    render: RenderOptions,
) -> Response:
    """Pinned tier: dispatch to one backend; its error propagates (no escalation)."""
    if tier == "httpx":
        return httpx_backend.attempt(method, url, headers, timeout, policy)
    if tier == "curl_cffi":
        return curl_backend.attempt(method, url, headers, timeout, policy, browser=browser)
    return playwright_backend.attempt(method, url, headers, timeout, policy, render=render)
