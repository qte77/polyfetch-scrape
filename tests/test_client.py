import logging
from collections.abc import Mapping

import httpx
import pytest
import respx

from polyfetch_scrape._backends import FingerprintBlock
from polyfetch_scrape.client import FetchError, fetch
from polyfetch_scrape.errors import GoneError, LegalBlock
from polyfetch_scrape.render_options import RenderOptions
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real sleeps so retry tests run fast."""
    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None)


@respx.mock
def test_fetch_returns_response_on_200() -> None:
    # Arrange
    url = "https://example.com/page"
    respx.get(url).mock(
        return_value=httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})
    )

    # Act
    resp = fetch(url)

    # Assert
    assert resp.status == 200
    assert resp.body == b"hello"
    assert resp.content_type == "text/plain"
    assert resp.backend == "httpx"
    assert resp.url == url


@respx.mock
def test_fetch_retries_then_succeeds() -> None:
    # Arrange
    url = "https://example.com/flaky"
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, content=b"ok"),
        ]
    )

    # Act
    resp = fetch(url)

    # Assert
    assert resp.status == 200
    assert resp.body == b"ok"
    assert route.call_count == 3


@respx.mock
def test_fetch_raises_after_max_attempts() -> None:
    # Arrange
    url = "https://example.com/dead"
    route = respx.get(url).mock(return_value=httpx.Response(503))
    policy = RetryPolicy(max_attempts=3)

    # Act / Assert
    with pytest.raises(FetchError):
        fetch(url, retry=policy)
    assert route.call_count == 3


@respx.mock
def test_fetch_retries_on_transport_error() -> None:
    # Arrange
    url = "https://example.com/conn"
    route = respx.get(url).mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, content=b"recovered"),
        ]
    )

    # Act
    resp = fetch(url)

    # Assert
    assert resp.status == 200
    assert resp.body == b"recovered"
    assert route.call_count == 2


@respx.mock
def test_fetch_raises_after_persistent_transport_error() -> None:
    url = "https://example.com/down"
    respx.get(url).mock(side_effect=httpx.ConnectError("nope"))

    with pytest.raises(FetchError):
        fetch(url, retry=RetryPolicy(max_attempts=2))


@respx.mock
def test_fetch_raises_goneerror_on_404() -> None:
    # Arrange
    url = "https://example.com/missing"
    route = respx.get(url).mock(return_value=httpx.Response(404, content=b"nope"))

    # Act / Assert: 404 is terminal — raises GoneError, not retried
    with pytest.raises(GoneError):
        fetch(url)
    assert route.call_count == 1


@respx.mock
def test_fetch_raises_legalblock_on_451_without_escalation() -> None:
    # Arrange
    url = "https://example.com/blocked-legally"
    route = respx.get(url).mock(return_value=httpx.Response(451))

    # Act / Assert: 451 raises LegalBlock from the httpx tier — never escalates (RFC 7725)
    with pytest.raises(LegalBlock):
        fetch(url)
    assert route.call_count == 1


@respx.mock
def test_fetch_sends_if_none_match_when_etag_given() -> None:
    # Arrange
    url = "https://example.com/etag"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b"ok"))

    # Act
    fetch(url, etag='"abc123"')

    # Assert
    sent = route.calls.last.request
    assert sent.headers["if-none-match"] == '"abc123"'


@respx.mock
def test_fetch_sends_if_modified_since_when_last_modified_given() -> None:
    # Arrange
    url = "https://example.com/last-modified"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b"ok"))

    # Act
    fetch(url, last_modified="Wed, 21 Oct 2015 07:28:00 GMT")

    # Assert
    sent = route.calls.last.request
    assert sent.headers["if-modified-since"] == "Wed, 21 Oct 2015 07:28:00 GMT"


@respx.mock
def test_fetch_returns_304_without_retry() -> None:
    # Arrange
    url = "https://example.com/poll"
    route = respx.get(url).mock(return_value=httpx.Response(304))

    # Act
    resp = fetch(url, etag='"abc123"')

    # Assert: 304 passes through as a Response, not retried/escalated
    assert resp.status == 304
    assert route.call_count == 1


@respx.mock
def test_fetch_caller_conditional_header_wins_over_kwarg() -> None:
    # Arrange
    url = "https://example.com/both"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b"ok"))

    # Act: caller supplies If-None-Match explicitly AND passes etag kwarg
    fetch(url, headers={"If-None-Match": '"caller"'}, etag='"kwarg"')

    # Assert: caller-supplied header wins
    sent = route.calls.last.request
    assert sent.headers["if-none-match"] == '"caller"'


def test_fetch_falls_back_to_curl_on_fingerprintblock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: httpx raises FingerprintBlock; curl returns a Response
    fallback_resp = Response(
        url="https://example.com",
        status=200,
        headers={},
        body=b"via-curl",
        content_type=None,
        backend="curl_cffi",
    )

    def fake_httpx_attempt(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        policy: RetryPolicy,
        **_kw: object,
    ) -> Response:
        raise FingerprintBlock("blocked")

    curl_calls: list[str] = []

    def fake_curl_attempt(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        policy: RetryPolicy,
        browser: str,
        **_kw: object,
    ) -> Response:
        curl_calls.append(browser)
        return fallback_resp

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)

    # Act
    resp = fetch("https://example.com")

    # Assert
    assert resp is fallback_resp
    assert resp.backend == "curl_cffi"
    assert curl_calls == ["chrome"]


def test_fetch_passes_browser_profile_to_curl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_httpx_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("blocked")

    def fake_curl_attempt(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        policy: RetryPolicy,
        browser: str,
        **_kw: object,
    ) -> Response:
        captured["browser"] = browser
        return Response(
            url=url, status=200, headers={}, body=b"", content_type=None, backend="curl_cffi"
        )

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)

    # Act
    fetch("https://example.com", browser="firefox")

    # Assert
    assert captured["browser"] == "firefox"


def test_fetch_raises_when_both_backends_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_httpx_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("httpx blocked")

    def fake_curl_attempt(*_a: object, **_kw: object) -> Response:
        raise FetchError("curl exhausted")

    def fake_patchright_attempt(*_a: object, **_kw: object) -> Response:
        raise FetchError("patchright also gave up")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)
    monkeypatch.setattr(
        "polyfetch_scrape._backends.patchright_backend.attempt", fake_patchright_attempt
    )

    with pytest.raises(FetchError):
        fetch("https://example.com")


def test_fetch_falls_through_to_patchright_when_curl_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw_resp = Response(
        url="https://example.com",
        status=200,
        headers={},
        body=b"<html/>",
        content_type="text/html",
        backend="patchright",
    )

    def fake_httpx_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("httpx blocked")

    def fake_curl_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("curl blocked")

    captured_kwargs: dict[str, object] = {}

    def fake_patchright_attempt(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        policy: RetryPolicy,
        render: RenderOptions | None = None,
    ) -> Response:
        captured_kwargs["wait_for_selector"] = render.wait_for_selector if render else None
        return pw_resp

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)
    monkeypatch.setattr(
        "polyfetch_scrape._backends.patchright_backend.attempt", fake_patchright_attempt
    )

    resp = fetch("https://example.com", wait_for_selector="#main")

    assert resp is pw_resp
    assert resp.backend == "patchright"
    assert captured_kwargs["wait_for_selector"] == "#main"


def test_fetch_logs_tier_escalation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_httpx_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("httpx blocked")

    def fake_curl_attempt(*_a: object, **_kw: object) -> Response:
        return Response(
            url="https://example.com",
            status=200,
            headers={},
            body=b"ok",
            content_type=None,
            backend="curl_cffi",
        )

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)

    with caplog.at_level(logging.INFO, logger="polyfetch_scrape"):
        resp = fetch("https://example.com")

    assert resp.backend == "curl_cffi"
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("curl_cffi" in r.getMessage() for r in info_records)


def _backend_response(backend: str) -> Response:
    return Response(
        url="https://example.com",
        status=200,
        headers={},
        body=b"<html/>",
        content_type="text/html",
        backend=backend,  # type: ignore[arg-type]
    )


def test_fetch_tier_pin_forces_patchright(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        calls["httpx"] += 1
        return _backend_response("httpx")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        calls["curl"] += 1
        return _backend_response("curl_cffi")

    def fake_pw(*_a: object, **_kw: object) -> Response:
        calls["pw"] += 1
        return _backend_response("patchright")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)
    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.attempt", fake_pw)

    resp = fetch("https://example.com", tier="patchright")

    assert resp.backend == "patchright"
    assert calls == {"httpx": 0, "curl": 0, "pw": 1}


def test_fetch_tier_pin_httpx_does_not_escalate(monkeypatch: pytest.MonkeyPatch) -> None:
    curl_called = False

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("blocked")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        nonlocal curl_called
        curl_called = True
        return _backend_response("curl_cffi")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)

    with pytest.raises(FingerprintBlock):
        fetch("https://example.com", tier="httpx")
    assert curl_called is False


def test_fetch_tier_pin_forces_curl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0}

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        calls["httpx"] += 1
        return _backend_response("httpx")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        calls["curl"] += 1
        return _backend_response("curl_cffi")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)

    resp = fetch("https://example.com", tier="curl_cffi")

    assert resp.backend == "curl_cffi"
    assert calls == {"httpx": 0, "curl": 1}


def test_fetch_forwards_render_to_patchright_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_pw(*_a: object, render: RenderOptions | None = None, **_kw: object) -> Response:
        captured["render"] = render
        return _backend_response("patchright")

    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.attempt", fake_pw)

    opts = RenderOptions(screenshot="viewport")
    fetch("https://example.com", tier="patchright", render=opts)

    assert captured["render"] == opts


@respx.mock
def test_fetch_forwards_json_body_to_httpx() -> None:
    import json as _json

    url = "https://example.com/api"
    route = respx.post(url).mock(return_value=httpx.Response(200, content=b"ok"))

    resp = fetch(url, method="POST", json={"limit": 20})

    assert resp.status == 200
    assert _json.loads(route.calls.last.request.content) == {"limit": 20}


def test_fetch_rejects_json_and_content_together() -> None:
    with pytest.raises(FetchError):
        fetch("https://example.com", json={"a": 1}, content=b"x")


def test_fetch_body_request_does_not_escalate_to_patchright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw_called = False

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("httpx blocked")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("curl blocked")

    def fake_pw(*_a: object, **_kw: object) -> Response:
        nonlocal pw_called
        pw_called = True
        return _backend_response("patchright")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)
    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.attempt", fake_pw)

    # Both fingerprint tiers block a POST with a body → clear FetchError, no patchright replay.
    with pytest.raises(FetchError) as exc_info:
        fetch("https://example.com", method="POST", json={"a": 1})

    assert pw_called is False
    assert not isinstance(exc_info.value, FingerprintBlock)


def test_fetch_tier_pin_patchright_rejects_body(monkeypatch: pytest.MonkeyPatch) -> None:
    pw_called = False

    def fake_pw(*_a: object, **_kw: object) -> Response:
        nonlocal pw_called
        pw_called = True
        return _backend_response("patchright")

    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.attempt", fake_pw)

    with pytest.raises(FetchError):
        fetch("https://example.com", tier="patchright", json={"a": 1})
    assert pw_called is False


def _install_tier_spies(monkeypatch: pytest.MonkeyPatch, calls: dict[str, int]) -> None:
    """Wire all three backends as counters; httpx/curl block, patchright returns."""

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        calls["httpx"] += 1
        raise FingerprintBlock("httpx blocked")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        calls["curl"] += 1
        raise FingerprintBlock("curl blocked")

    def fake_pw(*_a: object, **_kw: object) -> Response:
        calls["pw"] += 1
        return _backend_response("patchright")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)
    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.attempt", fake_pw)


def test_fetch_max_tier_caps_before_patchright(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}
    _install_tier_spies(monkeypatch, calls)

    # Both fingerprint tiers block, but max_tier caps at curl_cffi → never launch the browser.
    with pytest.raises(FetchError):
        fetch("https://example.com", max_tier="curl_cffi")

    assert calls == {"httpx": 1, "curl": 1, "pw": 0}


def test_fetch_min_tier_forces_patchright(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}
    _install_tier_spies(monkeypatch, calls)

    resp = fetch("https://example.com", min_tier="patchright")

    assert resp.backend == "patchright"
    assert calls == {"httpx": 0, "curl": 0, "pw": 1}


def test_fetch_min_tier_skips_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        calls["httpx"] += 1
        raise FingerprintBlock("httpx blocked")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        calls["curl"] += 1
        return _backend_response("curl_cffi")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)

    resp = fetch("https://example.com", min_tier="curl_cffi")

    assert resp.backend == "curl_cffi"
    assert calls == {"httpx": 0, "curl": 1, "pw": 0}


def test_fetch_rejects_min_tier_above_max_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}
    _install_tier_spies(monkeypatch, calls)

    with pytest.raises(FetchError):
        fetch("https://example.com", min_tier="patchright", max_tier="httpx")

    assert calls == {"httpx": 0, "curl": 0, "pw": 0}


def test_fetch_rejects_tier_combined_with_min_or_max(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}
    _install_tier_spies(monkeypatch, calls)

    with pytest.raises(FetchError):
        fetch("https://example.com", tier="httpx", min_tier="curl_cffi")

    assert calls == {"httpx": 0, "curl": 0, "pw": 0}


def test_fetch_body_with_max_tier_curl_never_reaches_patchright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}
    _install_tier_spies(monkeypatch, calls)

    # A POST body capped at curl_cffi: both block → FetchError, patchright never in range.
    with pytest.raises(FetchError):
        fetch("https://example.com", method="POST", json={"a": 1}, max_tier="curl_cffi")

    assert calls["pw"] == 0


def test_fetch_acquires_throttle_before_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _SpyThrottle:
        def acquire(self, url: str) -> None:
            events.append(f"acquire:{url}")

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        events.append("httpx")
        return _backend_response("httpx")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)

    fetch("https://ex.test/p", throttle=_SpyThrottle())  # type: ignore[arg-type]

    # Throttle is consulted once, for the request URL, before the backend runs.
    assert events == ["acquire:https://ex.test/p", "httpx"]
