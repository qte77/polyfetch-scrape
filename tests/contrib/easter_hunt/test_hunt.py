"""Orchestrator + SSRF-guard tests.

The fetch seam is monkeypatched at ``...easter_hunt.hunt.fetch`` (the name bound
in hunt.py's namespace) for logic tests; one respx-backed test drives the real
fetch chain end to end.
"""

import httpx
import pytest
import respx

from polyfetch_scrape._backends import FingerprintBlock
from polyfetch_scrape.contrib.easter_hunt.detectors import html_comments
from polyfetch_scrape.contrib.easter_hunt.orchestrator import _safe_fetch, hunt
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response

_FETCH = "polyfetch_scrape.contrib.easter_hunt.orchestrator.fetch"


def _resp(url: str, *, body: bytes = b"", headers: dict[str, str] | None = None) -> Response:
    return Response(
        url=url,
        status=200,
        headers=headers or {},
        body=body,
        content_type="text/html",
        backend="httpx",
    )


# --------------------------------------------------------------------------- #
# _safe_fetch
# --------------------------------------------------------------------------- #


def test_safe_fetch_returns_response_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_FETCH, lambda url, **_kw: _resp(url))
    result = _safe_fetch("https://a.test/", timeout=10.0)
    assert result is not None
    assert result.url == "https://a.test/"


def test_safe_fetch_swallows_fetcherror_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_kw: object) -> Response:
        raise FetchError("exhausted")

    monkeypatch.setattr(_FETCH, boom)
    assert _safe_fetch("https://a.test/", timeout=10.0) is None


def test_safe_fetch_swallows_fingerprintblock_subclass(monkeypatch: pytest.MonkeyPatch) -> None:
    # FingerprintBlock is a FetchError subclass; the broad except must catch it too.
    def boom(*_a: object, **_kw: object) -> Response:
        raise FingerprintBlock("blocked")

    monkeypatch.setattr(_FETCH, boom)
    assert _safe_fetch("https://a.test/", timeout=10.0) is None


def test_safe_fetch_passes_timeout_through(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    def spy(url: str, *, timeout: float) -> Response:
        captured["timeout"] = timeout
        return _resp(url)

    monkeypatch.setattr(_FETCH, spy)
    _safe_fetch("https://a.test/", timeout=3.5)
    assert captured["timeout"] == 3.5


# --------------------------------------------------------------------------- #
# hunt orchestration
# --------------------------------------------------------------------------- #


def test_hunt_no_seeds_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_FETCH, lambda url, **_kw: calls.append(url))
    assert hunt([]) == []
    assert calls == []  # nothing fetched


def test_hunt_no_paths_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_FETCH, lambda url, **_kw: calls.append(url))
    assert hunt(["https://a.test/"], paths=()) == []
    assert calls == []


def test_hunt_swallows_fetcherror_and_continues_to_next_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(url: str, **_kw: object) -> Response:
        if "bad" in url:
            raise FetchError("dead host")
        return _resp(url, body=b"<!-- we are hiring -->")

    monkeypatch.setattr(_FETCH, fake)

    findings = hunt(["https://bad.test/", "https://good.test/"], detectors=(html_comments,))

    assert [f.url for f in findings] == ["https://good.test/"]


def test_hunt_does_not_swallow_detector_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only fetch failures are swallowed; a bug in a detector must surface loudly.
    monkeypatch.setattr(_FETCH, lambda url, **_kw: _resp(url))

    def broken(_resp: Response) -> list[object]:
        raise RuntimeError("detector bug")

    with pytest.raises(RuntimeError, match="detector bug"):
        hunt(["https://a.test/"], detectors=(broken,))


def test_hunt_aggregates_findings_across_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_FETCH, lambda url, **_kw: _resp(url, body=b"<!-- join us -->"))

    findings = hunt(["https://a.test/", "https://b.test/"], detectors=(html_comments,))

    assert len(findings) == 2
    assert {f.url for f in findings} == {"https://a.test/", "https://b.test/"}


def test_hunt_builds_urls_seed_major_path_minor_without_double_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def spy(url: str, **_kw: object) -> Response:
        captured.append(url)
        return _resp(url)

    monkeypatch.setattr(_FETCH, spy)

    hunt(["https://a.test/", "https://b.test/"], paths=("/", "/about"), detectors=())

    assert captured == [
        "https://a.test/",
        "https://a.test/about",
        "https://b.test/",
        "https://b.test/about",
    ]


def test_hunt_passes_timeout_to_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    def spy(url: str, *, timeout: float) -> Response:
        captured["timeout"] = timeout
        return _resp(url)

    monkeypatch.setattr(_FETCH, spy)
    hunt(["https://a.test/"], detectors=(), timeout=7.5)
    assert captured["timeout"] == 7.5


def test_hunt_reuses_generator_detectors_across_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # detectors/paths are Iterable; a one-shot generator must not be exhausted after
    # the first seed. Guards against iterating the raw iterable per seed.
    monkeypatch.setattr(_FETCH, lambda url, **_kw: _resp(url, body=b"<!-- hiring -->"))

    detectors = (d for d in (html_comments,))  # single-use generator
    findings = hunt(["https://a.test/", "https://b.test/"], detectors=detectors)

    assert len(findings) == 2


# --------------------------------------------------------------------------- #
# SSRF guard — literal internal IPs raise ValueError BEFORE any fetch
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",  # is_loopback
        "http://10.0.0.1/",  # is_private (RFC1918 class A)
        "http://192.168.1.1/",  # is_private (RFC1918 class C)
        "http://172.16.0.1/",  # is_private (RFC1918 172.16/12, often forgotten)
        "http://169.254.169.254/",  # is_link_local (cloud IMDS — top SSRF target)
        "http://0.0.0.0/",  # is_unspecified (NOT covered by private|loopback|link_local)
        "http://224.0.0.1/",  # is_multicast
        "http://240.0.0.1/",  # is_reserved
        "http://[::1]/",  # IPv6 loopback (urlsplit strips brackets)
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 loopback
    ],
)
def test_hunt_ssrf_blocks_literal_internal_ip(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(_FETCH, lambda u, **_kw: calls.append(u))

    with pytest.raises(ValueError):  # noqa: PT011 - guard raises plain ValueError
        hunt([url])

    assert calls == []  # the guard fires BEFORE any network call


def test_hunt_ssrf_blocks_ip_with_embedded_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # urlsplit strips userinfo; hostname is still 127.0.0.1 -> blocked.
    calls: list[str] = []
    monkeypatch.setattr(_FETCH, lambda u, **_kw: calls.append(u))

    with pytest.raises(ValueError):  # noqa: PT011
        hunt(["http://user:pass@127.0.0.1/"])

    assert calls == []


def test_hunt_ssrf_passes_through_hostless_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # A malformed seed can yield a hostless URL (no IP to check); the guard must
    # pass it through, not crash on ipaddress.ip_address(None).
    captured: list[str] = []

    def spy(u: str, **_kw: object) -> Response:
        captured.append(u)
        return _resp(u)

    monkeypatch.setattr(_FETCH, spy)

    hunt(["/relative/seed"], detectors=())  # urljoin -> "/", hostname is None

    assert captured == ["/"]


def test_hunt_ssrf_raises_valueerror_not_fetcherror(monkeypatch: pytest.MonkeyPatch) -> None:
    # Must be ValueError, not FetchError — otherwise _safe_fetch would swallow it
    # and the scan would silently skip a blocked target.
    monkeypatch.setattr(_FETCH, lambda u, **_kw: _resp(u))
    with pytest.raises(ValueError) as exc_info:  # noqa: PT011
        hunt(["http://127.0.0.1/"])
    assert not isinstance(exc_info.value, FetchError)


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34/",  # public literal IP
        "http://example.com/",  # public DNS name (ip_address raises -> passes guard)
        "http://localhost/",  # DNS alias: literal-IP-only guard does NOT resolve it
    ],
)
def test_hunt_ssrf_allows_public_and_dns_hosts(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def spy(u: str, **_kw: object) -> Response:
        captured.append(u)
        return _resp(u)

    monkeypatch.setattr(_FETCH, spy)

    hunt([url], detectors=())

    assert len(captured) == 1  # guard passed through; fetch was reached


# --------------------------------------------------------------------------- #
# integration — real fetch chain via respx
# --------------------------------------------------------------------------- #


@respx.mock
def test_hunt_integration_drives_real_fetch_and_detectors() -> None:
    respx.get("https://a.test/").mock(
        return_value=httpx.Response(
            200, content=b"<!-- we are hiring -->", headers={"content-type": "text/html"}
        )
    )
    respx.get("https://b.test/").mock(
        return_value=httpx.Response(
            200, content=b"", headers={"x-clacks-overhead": "GNU Terry Pratchett"}
        )
    )

    findings = hunt(["https://a.test/", "https://b.test/"])  # default DETECTORS

    categories = {f.category for f in findings}
    assert "recruiting" in categories  # from a.test HTML comment
    assert "novelty" in categories  # from b.test x-clacks-overhead header
    assert isinstance(findings, list)


def test_hunt_default_detectors_are_the_three_detectors() -> None:
    # The default pack must wire exactly the three real detectors, in order — a typo
    # swapping or dropping one is caught here, unlike a len()/callable() smoke check.
    from polyfetch_scrape.contrib.easter_hunt.detectors import (
        DETECTORS,
        weird_headers,
        wellknown_present,
    )

    assert DETECTORS == (html_comments, weird_headers, wellknown_present)
