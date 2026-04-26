from collections.abc import Mapping

from polyfetch_scrape._backends import httpx_backend
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

__all__ = ["FetchError", "fetch"]


def fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
) -> Response:
    policy = retry if retry is not None else RetryPolicy()
    return httpx_backend.attempt(method, url, headers, timeout, policy)
