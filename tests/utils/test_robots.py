from collections.abc import Callable, Mapping

import pytest

from polyfetch_scrape.errors import FetchError, GoneError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils.robots import is_allowed

_RESOLVER = "polyfetch_scrape.utils._ssrf._resolve"


def _resp(
    body: bytes | str, *, url: str = "https://ex.com/robots.txt", ct: str = "text/plain"
) -> Response:
    raw = body if isinstance(body, bytes) else body.encode()
    return Response(url=url, status=200, headers={}, body=raw, content_type=ct, backend="httpx")


def _mapping_fetch(mapping: Mapping[str, Response]) -> Callable[..., Response]:
    def _fetch(url: str, **_kwargs: object) -> Response:
        if url in mapping:
            return mapping[url]
        raise GoneError(f"terminal HTTP 404: {url}", status=404)

    return _fetch


def _raising_fetch(exc: Exception) -> Callable[..., Response]:
    def _fetch(_url: str, **_kwargs: object) -> Response:
        raise exc

    return _fetch


def _patch(monkeypatch: pytest.MonkeyPatch, mapping: Mapping[str, Response]) -> None:
    # is_allowed() fetches robots.txt via utils.discovery.fetch_robots_txt_status, which
    # calls this module's `fetch` — reusing discovery's fetch+SSRF-guard pattern (#147).
    monkeypatch.setattr("polyfetch_scrape.utils.discovery.fetch", _mapping_fetch(mapping))


def test_wildcard_disallow_blocks_matching_path(monkeypatch: pytest.MonkeyPatch) -> None:
    robots = "User-agent: *\nDisallow: /private\n"
    _patch(monkeypatch, {"https://ex.com/robots.txt": _resp(robots)})

    assert is_allowed("https://ex.com/private/page") is False
    assert is_allowed("https://ex.com/public/page") is True


def test_specific_user_agent_rule_overrides_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    robots = "User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    _patch(monkeypatch, {"https://ex.com/robots.txt": _resp(robots)})

    assert is_allowed("https://ex.com/anything", user_agent="BadBot") is False
    assert is_allowed("https://ex.com/anything", user_agent="GoodBot") is True
    assert is_allowed("https://ex.com/anything") is True  # default user_agent="*"


def test_missing_robots_txt_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {})  # robots.txt 404s — no mapping entry

    assert is_allowed("https://ex.com/anything") is True


def test_html_soft_404_robots_txt_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = _resp("<!doctype html><html><body>not robots.txt</body></html>", ct="text/html")
    _patch(monkeypatch, {"https://ex.com/robots.txt": shell})

    assert is_allowed("https://ex.com/anything") is True


def test_bare_domain_seed_is_normalized_to_https(monkeypatch: pytest.MonkeyPatch) -> None:
    robots = "User-agent: *\nDisallow: /private\n"
    _patch(monkeypatch, {"https://ex.com/robots.txt": _resp(robots)})

    assert is_allowed("ex.com/private") is False


def test_robots_txt_itself_is_always_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # RFC 9309 §2.2.2: "The /robots.txt URI is implicitly allowed." is_allowed() checks the
    # path explicitly before any fetch/parse — assert fetch() is never even called, so this
    # is deterministic on every supported Python (3.11-3.14), unlike relying on whichever
    # urllib.robotparser version happens to special-case it (it doesn't, before 3.13/3.14).
    def _boom(*_a: object, **_kw: object) -> Response:
        raise AssertionError("fetch() must not be called for the /robots.txt path itself")

    monkeypatch.setattr("polyfetch_scrape.utils.discovery.fetch", _boom)

    assert is_allowed("https://ex.com/robots.txt") is True


@pytest.mark.parametrize("status", [400, 403, 404, 429])
def test_4xx_status_allows_everything(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    # RFC 9309 §2.3.1.3 "Unavailable" Status: any 4xx (incl. 404) means "the crawler MAY
    # access any resources on the server."
    monkeypatch.setattr(
        "polyfetch_scrape.utils.discovery.fetch",
        _raising_fetch(FetchError(f"terminal HTTP {status}", status=status)),
    )

    assert is_allowed("https://ex.com/anything") is True


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_status_disallows_everything(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    # RFC 9309 §2.3.1.4 "Unreachable" Status: a 5xx response means "the robots.txt file is
    # undefined and the crawler MUST assume complete disallow."
    monkeypatch.setattr(
        "polyfetch_scrape.utils.discovery.fetch",
        _raising_fetch(FetchError(f"server error {status}", status=status)),
    )

    assert is_allowed("https://ex.com/anything") is False


def test_network_failure_with_no_status_disallows_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RFC 9309 §2.3.1.4 also groups "server or network errors" (no HTTP response at all) with
    # a 5xx — both mean "the robots.txt file is undefined", not the §2.3.1.3 "Unavailable"
    # allow-all case. A FetchError with no status= models a transport-level failure (e.g. a
    # DNS/connection failure — see httpx_backend.py's TransportError handling).
    monkeypatch.setattr(
        "polyfetch_scrape.utils.discovery.fetch",
        _raising_fetch(FetchError("connection failed")),
    )

    assert is_allowed("https://ex.com/anything") is False


def test_ssrf_blocks_robots_txt_redirected_onto_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The origin is public, but the tier followed a 30x onto an RFC1918 host — is_allowed()
    # must refuse the landed response rather than parse it (same guard as discover(), #181).
    monkeypatch.setattr(
        _RESOLVER, lambda h: ["10.0.0.5"] if h == "intranet.test" else ["93.184.216.34"]
    )
    landed = _resp("User-agent: *\nAllow: /\n", url="http://intranet.test/robots.txt")
    _patch(monkeypatch, {"https://ex.com/robots.txt": landed})

    with pytest.raises(ValueError, match="SSRF"):
        is_allowed("https://ex.com/anything")


def test_ssrf_allows_internal_seed_redirected_to_another_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An internal seed (e.g. a local dev server) trusts everything reachable from it — a
    # robots.txt fetch landing on another internal address must not raise (it would for an
    # external seed, see test_ssrf_blocks_robots_txt_redirected_onto_internal_address above).
    landed = _resp("User-agent: *\nDisallow: /private\n", url="http://169.254.169.254/robots.txt")
    _patch(monkeypatch, {"http://127.0.0.1/robots.txt": landed})

    assert is_allowed("http://127.0.0.1/private") is False
    assert is_allowed("http://127.0.0.1/public") is True
