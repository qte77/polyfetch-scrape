import logging
from collections.abc import Mapping
from typing import Literal

from polyfetch_scrape._backends import (
    FingerprintBlock,
    curl_backend,
    httpx_backend,
    playwright_backend,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

__all__ = ["FetchError", "fetch"]

Browser = Literal["chrome", "firefox"]

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
) -> Response:
    policy = retry if retry is not None else RetryPolicy()
    try:
        return httpx_backend.attempt(method, url, headers, timeout, policy)
    except FingerprintBlock:
        _log.info("tier escalation: httpx blocked, trying curl_cffi: %s", url)
        try:
            return curl_backend.attempt(method, url, headers, timeout, policy, browser=browser)
        except FingerprintBlock:
            _log.info("tier escalation: curl_cffi blocked, trying playwright: %s", url)
            return playwright_backend.attempt(
                method, url, headers, timeout, policy, wait_for_selector=wait_for_selector
            )
