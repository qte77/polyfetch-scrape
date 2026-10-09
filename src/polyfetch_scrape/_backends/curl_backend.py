import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from curl_cffi import requests as curl_requests

from polyfetch_scrape._backends import (
    FingerprintBlock,
    bounded_diagnostics,
    is_suspected_soft_block,
    permanent_redirect_target,
    raise_for_terminal_status,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, next_delay, parse_retry_after, should_retry

Browser = Literal["chrome", "firefox"]

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: Response | None
    retry_status: int | None
    transport_error: Exception | None
    retry_after: float | None = None
    headers: dict[str, str] | None = None
    body_excerpt: str | None = None
    soft_block: bool = False


def attempt(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    browser: Browser = "chrome",
    *,
    json: Any | None = None,
    content: bytes | None = None,
) -> Response:
    last = _Attempt(None, None, None)
    session_cls = cast(Any, curl_requests).Session

    with session_cls(impersonate=browser) as session:
        for attempt_idx in range(policy.max_attempts):
            last = _attempt_once(session, method, url, headers, timeout, policy, json, content)
            if last.response is not None:
                return last.response
            if last.soft_block:
                break  # deterministic, not transient — retrying won't un-empty the body
            if attempt_idx + 1 < policy.max_attempts:
                time.sleep(next_delay(last.retry_after, policy, attempt_idx))

    diag: dict[str, Any] = {
        "status": last.retry_status,
        "headers": last.headers,
        "body_excerpt": last.body_excerpt,
    }
    if last.soft_block:
        msg = f"curl_cffi fetch: empty 2xx body — suspected soft block: {url}"
        raise FingerprintBlock(msg, **diag)

    detail = (
        f"status={last.retry_status}"
        if last.retry_status is not None
        else f"transport={last.transport_error!r}"
    )
    msg = f"curl_cffi fetch failed after {policy.max_attempts} attempts ({detail}): {url}"
    if last.retry_status in _FINGERPRINT_STATUSES:
        raise FingerprintBlock(msg, **diag) from last.transport_error
    raise FetchError(msg, **diag) from last.transport_error


def _attempt_once(
    session: Any,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    json: Any | None = None,
    content: bytes | None = None,
) -> _Attempt:
    try:
        http_resp = session.request(
            method,
            url,
            headers=dict(headers) if headers else None,
            timeout=timeout,
            json=json,
            data=content,
        )
    except Exception as exc:  # curl_cffi raises a wide error hierarchy
        return _Attempt(None, None, exc)

    status = int(http_resp.status_code)
    if should_retry(status, policy) or status in _FINGERPRINT_STATUSES:
        retry_after = parse_retry_after(http_resp.headers.get("retry-after"))
        resp_headers, body_excerpt = bounded_diagnostics(
            dict(http_resp.headers), bytes(http_resp.content)
        )
        return _Attempt(None, status, None, retry_after, resp_headers, body_excerpt)

    raise_for_terminal_status(status, url)
    resp = _to_response(http_resp, url, _header_value(headers, "user-agent"))
    if is_suspected_soft_block(method, resp.status, resp.body, resp.content_type):
        resp_headers, _ = bounded_diagnostics(resp.headers, resp.body)
        return _Attempt(None, status, None, None, resp_headers, None, soft_block=True)
    return _Attempt(resp, None, None)


def _header_value(headers: Mapping[str, str] | None, name: str) -> str | None:
    """Case-insensitive lookup over the headers *we* sent.

    curl_cffi's ``impersonate=`` profile injects its own browser-matching User-Agent
    natively (inside libcurl-impersonate) when the caller doesn't supply one — that value
    is never reflected back into Python, so this only ever resolves a caller-supplied
    override (see #198 / USING.md for the documented limitation).
    """
    if headers is None:
        return None
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


def _to_response(http_resp: Any, fallback_url: str, request_user_agent: str | None) -> Response:
    return Response(
        url=str(getattr(http_resp, "url", fallback_url)),
        status=int(http_resp.status_code),
        headers={str(k): str(v) for k, v in dict(http_resp.headers).items()},
        body=bytes(http_resp.content),
        content_type=dict(http_resp.headers).get("content-type"),
        backend="curl_cffi",
        permanent_redirect_to=permanent_redirect_target(
            int(http_resp.status_code), dict(http_resp.headers)
        ),
        request_user_agent=request_user_agent,
    )
