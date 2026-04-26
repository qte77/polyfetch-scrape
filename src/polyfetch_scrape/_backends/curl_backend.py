import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from curl_cffi import requests as curl_requests

from polyfetch_scrape._backends import FingerprintBlock
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, should_retry

Browser = Literal["chrome", "firefox"]

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: Response | None
    retry_status: int | None
    transport_error: Exception | None


def attempt(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    browser: Browser = "chrome",
) -> Response:
    last = _Attempt(None, None, None)
    session_cls = cast(Any, curl_requests).Session

    with session_cls(impersonate=browser) as session:
        for attempt_idx in range(policy.max_attempts):
            last = _attempt_once(session, method, url, headers, timeout, policy)
            if last.response is not None:
                return last.response
            if attempt_idx + 1 < policy.max_attempts:
                time.sleep(policy.backoff_initial * (policy.backoff_factor**attempt_idx))

    detail = (
        f"status={last.retry_status}"
        if last.retry_status is not None
        else f"transport={last.transport_error!r}"
    )
    msg = f"curl_cffi fetch failed after {policy.max_attempts} attempts ({detail}): {url}"
    if last.retry_status in _FINGERPRINT_STATUSES:
        raise FingerprintBlock(msg) from last.transport_error
    raise FetchError(msg) from last.transport_error


def _attempt_once(
    session: Any,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
) -> _Attempt:
    try:
        http_resp = session.request(
            method,
            url,
            headers=dict(headers) if headers else None,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — curl_cffi raises a wide error hierarchy
        return _Attempt(None, None, exc)

    status = int(http_resp.status_code)
    if should_retry(status, policy) or status in _FINGERPRINT_STATUSES:
        return _Attempt(None, status, None)

    return _Attempt(_to_response(http_resp, url), None, None)


def _to_response(http_resp: Any, fallback_url: str) -> Response:
    return Response(
        url=str(getattr(http_resp, "url", fallback_url)),
        status=int(http_resp.status_code),
        headers={str(k): str(v) for k, v in dict(http_resp.headers).items()},
        body=bytes(http_resp.content),
        content_type=dict(http_resp.headers).get("content-type"),
        backend="curl_cffi",
    )
