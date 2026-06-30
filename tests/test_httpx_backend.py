import httpx
import pytest
import respx

from polyfetch_scrape._backends import FingerprintBlock, httpx_backend
from polyfetch_scrape.retry import RetryPolicy
from polyfetch_scrape.utils.http_ua import STABLE_USER_AGENT


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None)


@respx.mock
def test_httpx_backend_raises_fingerprintblock_on_403() -> None:
    # Arrange
    url = "https://example.com/blocked"
    respx.get(url).mock(return_value=httpx.Response(403))

    # Act / Assert
    with pytest.raises(FingerprintBlock):
        httpx_backend.attempt(
            method="GET",
            url=url,
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )


@respx.mock
def test_httpx_backend_raises_fingerprintblock_on_tls_error() -> None:
    # Arrange: ConnectError carrying a TLS-flavoured message
    url = "https://example.com/tls"
    respx.get(url).mock(side_effect=httpx.ConnectError("[SSL: TLSV1_ALERT_INTERNAL_ERROR]"))

    # Act / Assert
    with pytest.raises(FingerprintBlock):
        httpx_backend.attempt(
            method="GET",
            url=url,
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )


@respx.mock
def test_httpx_backend_does_not_block_on_generic_connect_error() -> None:
    """A non-TLS transport error is a normal failure, not a fingerprint signal."""
    from polyfetch_scrape.errors import FetchError

    url = "https://example.com/conn"
    respx.get(url).mock(side_effect=httpx.ConnectError("Connection refused"))

    with pytest.raises(FetchError) as exc_info:
        httpx_backend.attempt(
            method="GET",
            url=url,
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )
    assert not isinstance(exc_info.value, FingerprintBlock)


@respx.mock
def test_httpx_backend_sets_default_user_agent_when_caller_omits() -> None:
    url = "https://example.com/ua-default"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    httpx_backend.attempt(
        method="GET",
        url=url,
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    sent = route.calls.last.request
    assert sent.headers["user-agent"] == STABLE_USER_AGENT


@respx.mock
def test_httpx_backend_preserves_caller_supplied_user_agent() -> None:
    url = "https://example.com/ua-supplied"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    httpx_backend.attempt(
        method="GET",
        url=url,
        headers={"User-Agent": "MyCustom/1.0"},
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    sent = route.calls.last.request
    assert sent.headers["user-agent"] == "MyCustom/1.0"


@respx.mock
def test_httpx_backend_preserves_caller_supplied_user_agent_case_insensitive() -> None:
    url = "https://example.com/ua-lowercase"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    httpx_backend.attempt(
        method="GET",
        url=url,
        headers={"user-agent": "lower/1.0"},
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    sent = route.calls.last.request
    assert sent.headers["user-agent"] == "lower/1.0"


@respx.mock
def test_httpx_backend_sets_default_accept_headers_when_caller_omits() -> None:
    url = "https://example.com/accept-default"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    httpx_backend.attempt(
        method="GET",
        url=url,
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    sent = route.calls.last.request
    assert sent.headers["accept"] == httpx_backend._DEFAULT_ACCEPT
    assert sent.headers["accept-language"] == httpx_backend._DEFAULT_ACCEPT_LANGUAGE


@respx.mock
def test_httpx_backend_preserves_caller_supplied_accept_headers() -> None:
    url = "https://example.com/accept-supplied"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    httpx_backend.attempt(
        method="GET",
        url=url,
        headers={"Accept": "application/json", "accept-language": "de-DE"},
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    sent = route.calls.last.request
    assert sent.headers["accept"] == "application/json"
    assert sent.headers["accept-language"] == "de-DE"
