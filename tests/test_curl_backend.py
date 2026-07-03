from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from curl_cffi import requests as curl_requests

from polyfetch_scrape._backends import FingerprintBlock, curl_backend
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape._backends.curl_backend.time.sleep", lambda _s: None)


def _fake_response(
    *,
    status: int,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
    url: str = "https://example.com",
) -> MagicMock:
    resp = MagicMock(spec=curl_requests.Response)
    resp.status_code = status
    resp.content = body
    resp.headers = dict(headers or {})
    resp.url = url
    return resp


def _install_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    side_effect: Any = None,
    return_value: Any = None,
) -> MagicMock:
    """Replace curl_cffi.requests.Session with a context-manager mock."""
    request_mock = MagicMock()
    if side_effect is not None:
        request_mock.side_effect = side_effect
    else:
        request_mock.return_value = return_value

    session_instance = MagicMock(spec=curl_requests.Session)
    session_instance.request = request_mock
    session_instance.__enter__ = MagicMock(return_value=session_instance)
    session_instance.__exit__ = MagicMock(return_value=False)

    session_cls = MagicMock(return_value=session_instance)
    monkeypatch.setattr(
        "polyfetch_scrape._backends.curl_backend.curl_requests.Session",
        session_cls,
    )
    return session_cls


def test_curl_backend_returns_response_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fake = _fake_response(status=200, body=b"ok", headers={"content-type": "text/plain"})
    session_cls = _install_session(monkeypatch, return_value=fake)

    # Act
    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    # Assert
    assert resp.status == 200
    assert resp.body == b"ok"
    assert resp.content_type == "text/plain"
    assert resp.backend == "curl_cffi"
    session_cls.assert_called_once_with(impersonate="chrome")


def test_curl_backend_retries_on_503_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fakes = [
        _fake_response(status=503),
        _fake_response(status=503),
        _fake_response(status=200, body=b"ok"),
    ]
    _install_session(monkeypatch, side_effect=fakes)

    # Act
    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=3),
    )

    # Assert
    assert resp.status == 200
    assert resp.body == b"ok"


def test_curl_backend_passes_firefox_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=200)
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        browser="firefox",
    )

    session_cls.assert_called_once_with(impersonate="firefox")


def test_curl_backend_raises_fetcherror_after_exhaust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=503)
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FetchError):
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )


def test_curl_backend_honors_retry_after_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "polyfetch_scrape._backends.curl_backend.time.sleep", lambda s: slept.append(s)
    )
    fakes = [
        _fake_response(status=503, headers={"retry-after": "3"}),
        _fake_response(status=200, body=b"ok"),
    ]
    _install_session(monkeypatch, side_effect=fakes)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    assert resp.status == 200
    assert slept == [3.0]


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [(401, AuthRequired), (404, GoneError), (451, LegalBlock)],
)
def test_curl_backend_raises_terminal_status(
    monkeypatch: pytest.MonkeyPatch, status: int, exc_type: type[Exception]
) -> None:
    fake = _fake_response(status=status)
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(exc_type):
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=3),
        )


def test_curl_backend_surfaces_permanent_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=301, headers={"location": "https://example.com/new"})
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com/old",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.status == 301
    assert resp.permanent_redirect_to == "https://example.com/new"


def test_curl_backend_raises_fingerprintblock_on_persistent_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=403)
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FingerprintBlock):
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )
