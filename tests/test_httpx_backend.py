import httpx
import pytest
import respx

from polyfetch_scrape._backends import FingerprintBlock, httpx_backend
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None
    )


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
