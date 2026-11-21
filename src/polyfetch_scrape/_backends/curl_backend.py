import ipaddress
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlOpt

from polyfetch_scrape._backends import (
    FingerprintBlock,
    bounded_diagnostics,
    is_success_status,
    is_suspected_soft_block,
    permanent_redirect_target,
    raise_for_terminal_status,
    redirect_target,
    unsuccessful_status_error,
)
from polyfetch_scrape._backends._stream import read_excerpt, save_streamed_body
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
    pinned_ip: str | None = None,
    pinned_host: str | None = None,
    stream_to: Path | None = None,
) -> Response:
    last = _Attempt(None, None, None)
    session_cls = cast(Any, curl_requests).Session
    session_kwargs = _session_kwargs(url, pinned_ip, pinned_host)

    with session_cls(impersonate=browser, **session_kwargs) as session:
        for attempt_idx in range(policy.max_attempts):
            last = _attempt_once(
                session,
                method,
                url,
                headers,
                timeout,
                policy,
                json,
                content,
                pinned_ip,
                stream_to,
            )
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
    pinned_ip: str | None = None,
    stream_to: Path | None = None,
) -> _Attempt:
    # allow_redirects IS a .request() parameter (unlike curl_options, see
    # _session_kwargs) — False returns the raw 3xx for manual hop-by-hop following
    # instead of libcurl auto-following onto an unchecked address.
    request_kwargs: dict[str, Any] = {"allow_redirects": False} if pinned_ip is not None else {}
    if stream_to is not None:
        request_kwargs["stream"] = True
    deadline = time.monotonic() + timeout
    try:
        http_resp = session.request(
            method,
            url,
            headers=dict(headers) if headers else None,
            timeout=timeout,
            json=json,
            data=content,
            **request_kwargs,
        )
    except Exception as exc:  # curl_cffi raises a wide error hierarchy
        return _Attempt(None, None, exc)

    if stream_to is None:
        return _settle(http_resp, method, url, headers, policy, pinned_ip)
    try:
        return _settle(
            http_resp, method, url, headers, policy, pinned_ip, stream_to, deadline, timeout
        )
    except FetchError:
        raise
    except Exception as exc:  # mid-body transport error or the deadline: retried as transport
        return _Attempt(None, None, exc)
    finally:
        http_resp.close()


def _settle(
    http_resp: Any,
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    policy: RetryPolicy,
    pinned_ip: str | None,
    stream_to: Path | None = None,
    deadline: float = 0.0,
    timeout: float = 0.0,
) -> _Attempt:
    """Classify a received response. When streaming, only a 2xx body is ever read in full,
    and only into ``stream_to``; error bodies are read up to the diagnostics cap."""
    if pinned_ip is not None:
        _verify_connected_to_pin(http_resp, pinned_ip, url)

    status = int(http_resp.status_code)
    if should_retry(status, policy) or status in _FINGERPRINT_STATUSES:
        retry_after = parse_retry_after(http_resp.headers.get("retry-after"))
        resp_headers, body_excerpt = bounded_diagnostics(
            dict(http_resp.headers), _diagnostic_body(http_resp, stream_to)
        )
        return _Attempt(None, status, None, retry_after, resp_headers, body_excerpt)

    raise_for_terminal_status(status, url)
    if not is_success_status(status):
        raise unsuccessful_status_error(
            status, url, dict(http_resp.headers), _diagnostic_body(http_resp, stream_to)
        )
    user_agent = _header_value(headers, "user-agent")
    if stream_to is not None:
        chunks = _within_deadline(http_resp.iter_content(), deadline, timeout, url)
        return _settle_streamed(http_resp, method, url, user_agent, chunks, stream_to)
    resp = _to_response(http_resp, url, user_agent, bytes(http_resp.content))
    if is_suspected_soft_block(method, resp.status, resp.body, resp.content_type):
        resp_headers, _ = bounded_diagnostics(resp.headers, resp.body)
        return _Attempt(None, status, None, None, resp_headers, None, soft_block=True)
    return _Attempt(resp, None, None)


def _settle_streamed(
    http_resp: Any,
    method: str,
    url: str,
    user_agent: str | None,
    chunks: Iterable[bytes],
    stream_to: Path,
) -> _Attempt:
    resp = _to_response(http_resp, url, user_agent, b"")
    if not 200 <= resp.status < 300:  # an unfollowed 3xx: returned as-is, nothing saved (#260)
        return _Attempt(resp, None, None)
    saved = save_streamed_body(method, resp.status, resp.content_type, chunks, stream_to, url)
    if saved is None:
        resp_headers, _ = bounded_diagnostics(resp.headers, b"")
        return _Attempt(None, resp.status, None, None, resp_headers, None, soft_block=True)
    size, sha256 = saved
    return _Attempt(
        replace(resp, saved_to=stream_to, saved_size=size, saved_sha256=sha256), None, None
    )


def _within_deadline(
    chunks: Iterable[bytes], deadline: float, timeout: float, url: str
) -> Iterator[bytes]:
    """Keep a buffered fetch's total-transfer cap when streaming.

    Measured on curl_cffi 0.17.0: a buffered request raises once the whole transfer
    passes ``timeout``, but a ``stream=True`` one only times out a stalled read, so a
    server dripping bytes slowly would hold it open indefinitely (#261).
    """
    for chunk in chunks:
        if time.monotonic() > deadline:
            raise TimeoutError(f"curl_cffi stream exceeded timeout={timeout}s: {url}")
        yield chunk


def _diagnostic_body(http_resp: Any, stream_to: Path | None) -> bytes:
    if stream_to is None:
        return bytes(http_resp.content)
    return read_excerpt(http_resp.iter_content())


def _session_kwargs(url: str, pinned_ip: str | None, pinned_host: str | None) -> dict[str, Any]:
    """``Session(...)`` CONSTRUCTOR kwargs for an optionally-pinned request.

    curl_cffi 0.17.0's ``Session.request()`` has no ``curl_options`` parameter and no
    ``**kwargs`` (confirmed via ``inspect.signature``) — only ``BaseSession.__init__``
    (the constructor) accepts it. An earlier version of this fix spread
    ``curl_options=...`` into ``.request(...)`` instead: every pinned request raised
    ``TypeError``, silently caught by ``_attempt_once``'s broad ``except Exception``
    and surfaced as an ordinary ``FetchError`` — the pin never actually took effect.
    One ``Session`` is already created per ``attempt()`` call (one per hop, since
    ``guarded_fetch`` calls ``attempt`` fresh for each redirect), so building the
    RESOLVE override here (not per-retry) is correct and cheap.

    No pin → ``{}``, so the unpinned path's session construction is byte-for-byte
    unchanged. With a pin:

    - ``CurlOpt.RESOLVE`` (#240 scope a) makes curl's own resolver answer
      ``pinned_host:port`` with ``pinned_ip`` for this session's lifetime. The URL
      itself is unchanged: curl resolves the given host internally via this override,
      so Host/SNI/cert verification are unaffected (they already use the URL's own
      host). ``allow_redirects=False`` (a ``.request()``-level kwarg; see
      ``_attempt_once``) returns the raw 3xx for manual hop-by-hop following instead
      of libcurl auto-following onto an unchecked address.
    - ``trust_env=False`` disables curl's own ``http_proxy``/``https_proxy``
      environment lookup for this session. A pin that still honours a configured
      proxy is no pin at all — the connection would go to the proxy, not the
      verified address — so the pinned path never trusts the environment for
      routing.

    The RESOLVE entry's HOST part is IDNA-encoded (``pinned_host`` arrives as the raw,
    possibly-unicode hostname ``urlsplit`` gave the caller; curl looks the entry up by
    the ASCII/punycode form it resolves internally, so the two must match or the
    override silently misses and curl falls back to its own DNS). The ADDRESS part is
    bracketed for IPv6, per curl.se's ``CURLOPT_RESOLVE`` (``[+]HOST:PORT:ADDRESS``) —
    only the address, never the host, needs brackets.
    """
    if pinned_ip is None or pinned_host is None:
        return {}
    port = urlsplit(url).port or (443 if url.startswith("https") else 80)
    ascii_host = pinned_host.encode("idna").decode("ascii")
    address = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
    return {
        "curl_options": {CurlOpt.RESOLVE: [f"{ascii_host}:{port}:{address}"]},
        "trust_env": False,
    }


def _unmap(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> Any:
    """The embedded IPv4 address of an IPv4-mapped IPv6 literal, else ``addr`` unchanged.

    Local to this module (not imported from ``utils._ssrf``, which imports
    ``client`` → this module — importing back would cycle).
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _verify_connected_to_pin(http_resp: Any, pinned_ip: str, url: str) -> None:
    """Refuse the response if curl did not actually connect to the pinned address.

    ``CurlOpt.RESOLVE`` can silently miss (a parser differential between ``urlsplit``
    — what the SSRF guard checked — and curl's own URL/host parsing: a backslash,
    userinfo, or percent-encoding quirk), in which case curl falls back to its own
    DNS for the real request. Comparing curl's own ``primary_ip`` (the address it
    actually connected to, ``curl_cffi.requests.Response.primary_ip``) against the
    pin — both normalised through :mod:`ipaddress` so an IPv4-mapped IPv6 form still
    matches its plain-IPv4 pin — means the pin can never be silently bypassed (#240).
    """
    reported = str(getattr(http_resp, "primary_ip", "") or "").strip("[]")
    try:
        actual = _unmap(ipaddress.ip_address(reported))
        expected = _unmap(ipaddress.ip_address(pinned_ip))
    except ValueError:
        raise FetchError(
            f"SSRF guard: could not verify the connected address for {url!r} "
            f"(pinned {pinned_ip!r}, curl reported {reported!r})"
        ) from None
    if actual != expected:
        raise FetchError(
            f"SSRF guard: curl connected to {reported!r} but {pinned_ip!r} was pinned "
            f"for {url!r} — refusing the response"
        )


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


def _to_response(
    http_resp: Any, fallback_url: str, request_user_agent: str | None, body: bytes
) -> Response:
    return Response(
        url=str(getattr(http_resp, "url", fallback_url)),
        status=int(http_resp.status_code),
        headers={str(k): str(v) for k, v in dict(http_resp.headers).items()},
        body=body,
        content_type=dict(http_resp.headers).get("content-type"),
        backend="curl_cffi",
        permanent_redirect_to=permanent_redirect_target(
            int(http_resp.status_code), dict(http_resp.headers)
        ),
        request_user_agent=request_user_agent,
        redirect_to=redirect_target(int(http_resp.status_code), dict(http_resp.headers)),
    )
