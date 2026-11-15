from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from curl_cffi import requests as curl_requests
from curl_cffi.const import CurlOpt

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
    primary_ip: str = "",
) -> MagicMock:
    resp = MagicMock(spec=curl_requests.Response)
    resp.status_code = status
    resp.content = body
    resp.headers = dict(headers or {})
    resp.url = url
    resp.primary_ip = primary_ip
    return resp


def _install_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    side_effect: Any = None,
    return_value: Any = None,
) -> MagicMock:
    """Replace curl_cffi.requests.Session with a signature-checked mock.

    ``create_autospec(curl_requests.Session)`` (the class, not an ``instance=True``
    object) makes every ``.request(...)`` call validated against curl_cffi 0.17.0's
    real ``Session.request`` signature — a bad kwarg (e.g. ``curl_options=``, which
    ``.request`` does not accept; it's a ``Session``-constructor-only parameter)
    raises ``TypeError`` instead of silently succeeding. A bare ``MagicMock`` here
    previously masked exactly that bug (#295 round 4): every pinned curl request
    raised ``TypeError`` in production, caught by ``_attempt_once``'s broad
    ``except Exception`` and surfaced as an ordinary ``FetchError``, while the
    mocked ``.request`` accepted the invalid kwarg without complaint.
    """
    session_cls = create_autospec(curl_requests.Session)
    session_instance = session_cls.return_value
    if side_effect is not None:
        session_instance.request.side_effect = side_effect
    else:
        session_instance.request.return_value = return_value
    session_instance.__enter__ = MagicMock(return_value=session_instance)
    session_instance.__exit__ = MagicMock(return_value=False)

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


def test_curl_backend_response_user_agent_is_none_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """curl_cffi's impersonation profile picks a UA natively; we can't read it back (#198)."""
    fake = _fake_response(status=200, body=b"ok")
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.request_user_agent is None


def test_curl_backend_response_carries_caller_supplied_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"ok")
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers={"User-Agent": "MyCustom/1.0"},
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.request_user_agent == "MyCustom/1.0"


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


@pytest.mark.parametrize("status", [400, 418, 999])
def test_curl_backend_raises_on_non_success_status(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A final status outside 2xx/3xx is an error with diagnostics, not a Response (#254)."""
    fake = _fake_response(status=status, body=b"login wall", headers={"set-cookie": "s=1"})
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FetchError) as info:
        curl_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )

    assert type(info.value) is FetchError
    assert info.value.status == status
    assert info.value.body_excerpt == "login wall"
    assert info.value.headers == {}  # Set-Cookie redacted


def test_curl_backend_surfaces_temporary_redirect_target(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_response(status=307, headers={"Location": "https://example.com/tmp"})
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com/old",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.permanent_redirect_to is None
    assert resp.redirect_to == "https://example.com/tmp"  # any 3xx Location (#260)


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


def test_curl_backend_pins_via_curl_options_resolve_and_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#240 scope (a): CurlOpt.RESOLVE is a Session-CONSTRUCTOR kwarg (curl_cffi
    0.17.0's ``Session.request`` has no ``curl_options`` param); ``allow_redirects``
    stays a ``.request()`` kwarg."""
    fake = _fake_response(status=200, body=b"ok", primary_ip="93.184.216.34")
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="GET",
        url="https://public.test/x",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip="93.184.216.34",
        pinned_host="public.test",
    )

    session_kwargs = session_cls.call_args.kwargs
    assert session_kwargs["curl_options"] == {CurlOpt.RESOLVE: ["public.test:443:93.184.216.34"]}
    assert session_kwargs["trust_env"] is False
    request_kwargs = session_cls.return_value.request.call_args.kwargs
    assert request_kwargs["allow_redirects"] is False
    assert "curl_options" not in request_kwargs


def test_curl_backend_pin_resolve_uses_the_urls_own_port_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"ok", primary_ip="93.184.216.34")
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="GET",
        url="http://public.test:8080/x",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip="93.184.216.34",
        pinned_host="public.test",
    )

    session_kwargs = session_cls.call_args.kwargs
    assert session_kwargs["curl_options"] == {CurlOpt.RESOLVE: ["public.test:8080:93.184.216.34"]}


def test_curl_backend_unpinned_path_omits_resolve_and_redirect_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"ok")
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    session_kwargs = session_cls.call_args.kwargs
    assert "curl_options" not in session_kwargs
    assert "trust_env" not in session_kwargs
    request_kwargs = session_cls.return_value.request.call_args.kwargs
    assert "allow_redirects" not in request_kwargs


def test_curl_backend_resolve_entry_brackets_an_ipv6_pinned_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # curl.se CURLOPT_RESOLVE: an IPv6 ADDRESS needs [brackets]; the HOST part doesn't.
    ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
    fake = _fake_response(status=200, body=b"ok", primary_ip=ipv6)
    session_cls = _install_session(monkeypatch, return_value=fake)

    curl_backend.attempt(
        method="GET",
        url="https://public.test/x",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip=ipv6,
        pinned_host="public.test",
    )

    session_kwargs = session_cls.call_args.kwargs
    assert session_kwargs["curl_options"] == {CurlOpt.RESOLVE: [f"public.test:443:[{ipv6}]"]}


def test_curl_backend_resolve_entry_idna_encodes_a_unicode_pinned_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pinned_host arrives as the raw (possibly unicode) hostname from urlsplit; curl
    # itself will look it up as the ASCII/punycode form, so the RESOLVE entry's HOST
    # part must match that, not the unicode original.
    fake = _fake_response(status=200, body=b"ok", primary_ip="93.184.216.34")
    session_cls = _install_session(monkeypatch, return_value=fake)
    unicode_host = "тест.test"
    ascii_host = unicode_host.encode("idna").decode("ascii")

    curl_backend.attempt(
        method="GET",
        url="https://public.test/x",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip="93.184.216.34",
        pinned_host=unicode_host,
    )

    session_kwargs = session_cls.call_args.kwargs
    assert session_kwargs["curl_options"] == {CurlOpt.RESOLVE: [f"{ascii_host}:443:93.184.216.34"]}


def test_curl_backend_raises_when_primary_ip_does_not_match_the_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Catches any parser differential between urlsplit (what the SSRF guard checked)
    # and curl's own parsing, and any RESOLVE miss — the pin can't be silently bypassed.
    fake = _fake_response(status=200, body=b"ok", primary_ip="127.0.0.1")
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FetchError) as excinfo:
        curl_backend.attempt(
            method="GET",
            url="https://public.test/x",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
            pinned_ip="93.184.216.34",
            pinned_host="public.test",
        )

    assert "93.184.216.34" in str(excinfo.value)
    assert "127.0.0.1" in str(excinfo.value)


def test_curl_backend_primary_ip_check_normalizes_an_ipv4_mapped_ipv6_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_response(status=200, body=b"ok", primary_ip="::ffff:93.184.216.34")
    _install_session(monkeypatch, return_value=fake)

    # must not raise — the IPv4-mapped IPv6 form curl reported is the same address
    # as the plain IPv4 pin
    resp = curl_backend.attempt(
        method="GET",
        url="https://public.test/x",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip="93.184.216.34",
        pinned_host="public.test",
    )

    assert resp.status == 200


def test_curl_backend_raises_when_primary_ip_is_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # curl reported no usable primary_ip at all (empty/garbage) — refuse rather
    # than assume the connection landed on the pinned address.
    fake = _fake_response(status=200, body=b"ok", primary_ip="")
    _install_session(monkeypatch, return_value=fake)

    with pytest.raises(FetchError, match=r"93\.184\.216\.34"):
        curl_backend.attempt(
            method="GET",
            url="https://public.test/x",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
            pinned_ip="93.184.216.34",
            pinned_host="public.test",
        )


def test_curl_backend_pin_really_connects_to_the_pinned_address(loopback_server: int) -> None:
    """Real proof, no mocks (#295 round 4): a prior version of this fix spread
    ``curl_options`` into ``.request(...)``, which curl_cffi 0.17.0 silently rejects
    — every pinned request failed in production while the suite's bare-MagicMock
    ``.request`` stayed green. No ``Session``/``.request`` replacement here at all;
    this is the real ``curl_cffi.requests.Session`` talking to a real socket. libcurl
    resolves DNS in C, bypassing Python's ``socket`` module entirely, so the suite's
    autouse DNS stub (``tests/conftest.py``) has no effect on it either way.

    ``pin-test-curl.invalid`` is RFC 2606-reserved (guaranteed to never resolve in
    any real DNS), so a genuine response with this exact body can only mean curl
    actually used the ``CurlOpt.RESOLVE`` override to reach 127.0.0.1 — not its own
    DNS, which has nothing to find for this host. This also exercises
    ``_verify_connected_to_pin`` for real: it must see ``primary_ip == "127.0.0.1"``
    and not raise.
    """
    host = "pin-test-curl.invalid"

    resp = curl_backend.attempt(
        method="GET",
        url=f"http://{host}:{loopback_server}/",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        pinned_ip="127.0.0.1",
        pinned_host=host,
    )

    assert resp.status == 200
    assert resp.body == b"ok-from-loopback"


def test_curl_backend_unpinned_path_skips_the_primary_ip_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No pin → no primary_ip verification; an empty/garbage primary_ip must not raise.
    fake = _fake_response(status=200, body=b"ok", primary_ip="")
    _install_session(monkeypatch, return_value=fake)

    resp = curl_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.status == 200


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
