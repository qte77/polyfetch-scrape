import logging
from collections.abc import Mapping

import httpx
import pytest
import respx

from polyfetch_scrape._backends import FingerprintBlock
from polyfetch_scrape.client import FetchError, fetch
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
def test_fetch_does_not_retry_on_404() -> None:
    # Arrange
    url = "https://example.com/missing"
    route = respx.get(url).mock(return_value=httpx.Response(404, content=b"nope"))

    # Act
    resp = fetch(url)

    # Assert: 404 is a terminal status, not retried
    assert resp.status == 404
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

    def fake_playwright_attempt(*_a: object, **_kw: object) -> Response:
        raise FetchError("playwright also gave up")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)
    monkeypatch.setattr(
        "polyfetch_scrape._backends.playwright_backend.attempt", fake_playwright_attempt
    )

    with pytest.raises(FetchError):
        fetch("https://example.com")


def test_fetch_falls_through_to_playwright_when_curl_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw_resp = Response(
        url="https://example.com",
        status=200,
        headers={},
        body=b"<html/>",
        content_type="text/html",
        backend="playwright",
    )

    def fake_httpx_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("httpx blocked")

    def fake_curl_attempt(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("curl blocked")

    captured_kwargs: dict[str, object] = {}

    def fake_playwright_attempt(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        timeout: float,
        policy: RetryPolicy,
        wait_for_selector: str | None = None,
    ) -> Response:
        captured_kwargs["wait_for_selector"] = wait_for_selector
        return pw_resp

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx_attempt)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl_attempt)
    monkeypatch.setattr(
        "polyfetch_scrape._backends.playwright_backend.attempt", fake_playwright_attempt
    )

    resp = fetch("https://example.com", wait_for_selector="#main")

    assert resp is pw_resp
    assert resp.backend == "playwright"
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


def test_fetch_tier_pin_forces_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"httpx": 0, "curl": 0, "pw": 0}

    def fake_httpx(*_a: object, **_kw: object) -> Response:
        calls["httpx"] += 1
        return _backend_response("httpx")

    def fake_curl(*_a: object, **_kw: object) -> Response:
        calls["curl"] += 1
        return _backend_response("curl_cffi")

    def fake_pw(*_a: object, **_kw: object) -> Response:
        calls["pw"] += 1
        return _backend_response("playwright")

    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.attempt", fake_httpx)
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.attempt", fake_curl)
    monkeypatch.setattr("polyfetch_scrape._backends.playwright_backend.attempt", fake_pw)

    resp = fetch("https://example.com", tier="playwright")

    assert resp.backend == "playwright"
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
