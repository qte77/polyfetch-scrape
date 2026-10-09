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
    fake = _fake_response(status=200, body=b"ok")  # non-empty: not the #237 soft-block case
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


def test_curl_backend_fingerprintblock_carries_bounded_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(
        status=403,
        body=b"<html>blocked</html>",
        headers={"content-type": "text/html", "set-cookie": "sid=abc123"},
    )
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FingerprintBlock) as excinfo:
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )

    exc = excinfo.value
    assert exc.status == 403
    assert exc.headers == {"content-type": "text/html"}  # set-cookie redacted
    assert exc.body_excerpt == "<html>blocked</html>"


def test_curl_backend_fetcherror_on_exhaustion_carries_bounded_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=503, body=b"rate limited", headers={"content-type": "text/plain"})
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FetchError) as excinfo:
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )

    exc = excinfo.value
    assert exc.status == 503
    assert exc.headers == {"content-type": "text/plain"}
    assert exc.body_excerpt == "rate limited"


def test_curl_backend_body_excerpt_capped_at_2kb(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=403, body=b"x" * 3000)
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FingerprintBlock) as excinfo:
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )

    assert excinfo.value.body_excerpt is not None
    assert len(excinfo.value.body_excerpt) == 2048


def test_curl_backend_empty_2xx_html_body_raises_fingerprintblock_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"", headers={"content-type": "text/html"})
    session_cls = _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FingerprintBlock) as excinfo:
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=3),
        )

    assert excinfo.value.status == 200
    # Deterministic soft block — no point retrying within the tier.
    assert session_cls.return_value.request.call_count == 1


def test_curl_backend_empty_2xx_missing_content_type_raises_fingerprintblock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"")
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FingerprintBlock):
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )


@pytest.mark.parametrize(
    ("method", "status", "body", "headers"),
    [
        ("GET", 204, b"", {}),
        ("HEAD", 200, b"", {}),
        ("GET", 200, b"", {"content-type": "application/json"}),
        ("GET", 200, b"non-empty", {"content-type": "text/html"}),
    ],
)
def test_curl_backend_does_not_soft_block_exempt_cases(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    status: int,
    body: bytes,
    headers: dict[str, str],
) -> None:
    fake = _fake_response(status=status, body=body, headers=headers)
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method=method,
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.status == status


def test_curl_backend_forwards_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=200, body=b"ok")
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="POST",
        url="https://example.com/api",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        json={"q": "x"},
    )

    kwargs = session_cls.return_value.request.call_args.kwargs
    assert kwargs["json"] == {"q": "x"}
    assert kwargs["data"] is None


def test_curl_backend_forwards_raw_content_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=200, body=b"ok")
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="POST",
        url="https://example.com/raw",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        content=b"raw-bytes",
    )

    kwargs = session_cls.return_value.request.call_args.kwargs
    assert kwargs["data"] == b"raw-bytes"
    assert kwargs["json"] is None
