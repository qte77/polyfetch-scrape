import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from polyfetch_scrape._backends import FingerprintBlock
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, should_retry

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


def _is_tls_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "ssl" in msg or "tls" in msg or "certificate" in msg


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
) -> Response:
    last = _Attempt(None, None, None)

    with httpx.Client(timeout=timeout) as client:
        for attempt_idx in range(policy.max_attempts):
            last = _attempt_once(client, method, url, headers, policy)
            if last.response is not None:
                return last.response
            if attempt_idx + 1 < policy.max_attempts:
                time.sleep(policy.backoff_initial * (policy.backoff_factor**attempt_idx))

    detail = (
        f"status={last.retry_status}"
        if last.retry_status is not None
        else f"transport={last.transport_error!r}"
    )
    msg = f"httpx fetch failed after {policy.max_attempts} attempts ({detail}): {url}"

    if last.retry_status in _FINGERPRINT_STATUSES or (
        last.transport_error is not None and _is_tls_error(last.transport_error)
    ):
        raise FingerprintBlock(msg) from last.transport_error
    raise FetchError(msg) from last.transport_error


def _attempt_once(
    client: httpx.Client,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    policy: RetryPolicy,
) -> _Attempt:
    try:
        http_resp = client.request(method, url, headers=dict(headers) if headers else None)
    except httpx.TransportError as exc:
        return _Attempt(None, None, exc)

    if (
        should_retry(http_resp.status_code, policy)
        or http_resp.status_code in _FINGERPRINT_STATUSES
    ):
        return _Attempt(None, http_resp.status_code, None)

    return _Attempt(_to_response(http_resp), None, None)


def _to_response(http_resp: httpx.Response) -> Response:
    return Response(
        url=str(http_resp.url),
        status=http_resp.status_code,
        headers=dict(http_resp.headers),
        body=http_resp.content,
        content_type=http_resp.headers.get("content-type"),
        backend="httpx",
    )
