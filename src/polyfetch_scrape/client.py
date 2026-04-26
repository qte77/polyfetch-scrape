from collections.abc import Mapping
from typing import Literal

from polyfetch_scrape._backends import FingerprintBlock, curl_backend, httpx_backend
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

__all__ = ["FetchError", "fetch"]

Browser = Literal["chrome", "firefox"]


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    browser: Browser = "chrome",
) -> Response:
    policy = retry if retry is not None else RetryPolicy()
    try:
        return httpx_backend.attempt(method, url, headers, timeout, policy)
    except FingerprintBlock:
        return curl_backend.attempt(method, url, headers, timeout, policy, browser=browser)
