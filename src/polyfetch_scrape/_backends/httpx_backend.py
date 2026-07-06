import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from polyfetch_scrape._backends import (
    FingerprintBlock,
    permanent_redirect_target,
    raise_for_terminal_status,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, next_delay, parse_retry_after, should_retry
from polyfetch_scrape.utils.http_ua import STABLE_USER_AGENT

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


def _is_tls_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "ssl" in msg or "tls" in msg or "certificate" in msg


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: Response | None
    retry_status: int | None
    transport_error: Exception | None
    retry_after: float | None = None


def attempt(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    *,
    json: Any | None = None,
    content: bytes | None = None,
) -> Response:
    last = _Attempt(None, None, None)

    with httpx.Client(timeout=timeout) as client:
        for attempt_idx in range(policy.max_attempts):
            last = _attempt_once(client, method, url, headers, policy, json, content)
            if last.response is not None:
                return last.response
            if attempt_idx + 1 < policy.max_attempts:
                time.sleep(next_delay(last.retry_after, policy, attempt_idx))

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
    json: Any | None = None,
    content: bytes | None = None,
) -> _Attempt:
    try:
        http_resp = client.request(
            method, url, headers=_with_default_headers(headers), json=json, content=content
        )
    except httpx.TransportError as exc:
        return _Attempt(None, None, exc)

    if (
        should_retry(http_resp.status_code, policy)
        or http_resp.status_code in _FINGERPRINT_STATUSES
    ):
        retry_after = parse_retry_after(http_resp.headers.get("retry-after"))
        return _Attempt(None, http_resp.status_code, None, retry_after)

    raise_for_terminal_status(http_resp.status_code, url)
    return _Attempt(_to_response(http_resp), None, None)


_DEFAULT_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
)
_DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def _with_default_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Inject browser-default ``User-Agent``/``Accept``/``Accept-Language`` when omitted.

    httpx's defaults (``python-httpx/X.Y.Z`` UA, ``Accept: */*``, no ``Accept-Language``)
    are immediate bot tells that defeat the cheap httpx tier before TLS-fingerprint
    fallback would even matter. Caller-supplied values (any case) win.
    """
    merged: dict[str, str] = dict(headers) if headers else {}
    if not any(k.lower() == "user-agent" for k in merged):
        merged["User-Agent"] = STABLE_USER_AGENT
    if not any(k.lower() == "accept" for k in merged):
        merged["Accept"] = _DEFAULT_ACCEPT
    if not any(k.lower() == "accept-language" for k in merged):
        merged["Accept-Language"] = _DEFAULT_ACCEPT_LANGUAGE
    return merged


def _to_response(http_resp: httpx.Response) -> Response:
    return Response(
        url=str(http_resp.url),
        status=http_resp.status_code,
        headers=dict(http_resp.headers),
        body=http_resp.content,
        content_type=http_resp.headers.get("content-type"),
        backend="httpx",
        permanent_redirect_to=permanent_redirect_target(http_resp.status_code, http_resp.headers),
    )
