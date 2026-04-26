import httpx
import pytest
import respx

from polyfetch_scrape.client import FetchError, fetch
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real sleeps so retry tests run fast."""
    monkeypatch.setattr("polyfetch_scrape.client.time.sleep", lambda _s: None)


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
