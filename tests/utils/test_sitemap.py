import gzip
from collections.abc import Callable, Mapping

import httpx
import pytest
import respx

from polyfetch_scrape.errors import GoneError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils.sitemap import fetch_sitemap_urls

_NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard the respx integration test against any tier-escalation backoff sleeps.
    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None)


def _urlset(*locs: str) -> bytes:
    body = "".join(f"<url><loc>{u}</loc></url>" for u in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {_NS}>{body}</urlset>'.encode()


def _index(*locs: str) -> bytes:
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex {_NS}>{body}</sitemapindex>'.encode()
    )


def _resp(
    body: bytes, *, url: str = "https://ex.com/sitemap.xml", content_type: str = "application/xml"
) -> Response:
    return Response(
        url=url, status=200, headers={}, body=body, content_type=content_type, backend="httpx"
    )


def _mapping_fetch(mapping: Mapping[str, Response]) -> Callable[..., Response]:
    def _fetch(url: str, **_kwargs: object) -> Response:
        if url in mapping:
            return mapping[url]
        raise GoneError(f"terminal HTTP 404: {url}", status=404)

    return _fetch


def test_flat_sitemap_returns_loc_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _mapping_fetch(
        {"https://ex.com/sitemap.xml": _resp(_urlset("https://ex.com/a", "https://ex.com/b"))}
    )
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", fake)

    assert fetch_sitemap_urls("https://ex.com") == ["https://ex.com/a", "https://ex.com/b"]


def test_sitemap_index_follows_children(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {
        "https://ex.com/sitemap.xml": _resp(_index("https://ex.com/c1.xml")),
        "https://ex.com/c1.xml": _resp(
            _urlset("https://ex.com/p1", "https://ex.com/p2"), url="https://ex.com/c1.xml"
        ),
    }
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", _mapping_fetch(mapping))

    assert fetch_sitemap_urls("https://ex.com") == ["https://ex.com/p1", "https://ex.com/p2"]


def test_gzip_sitemap_is_decompressed(monkeypatch: pytest.MonkeyPatch) -> None:
    gz = gzip.compress(_urlset("https://ex.com/g"))
    fake = _mapping_fetch(
        {"https://ex.com/sitemap.xml": _resp(gz, content_type="application/gzip")}
    )
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", fake)

    assert fetch_sitemap_urls("https://ex.com") == ["https://ex.com/g"]


def test_max_urls_caps_result(monkeypatch: pytest.MonkeyPatch) -> None:
    locs = [f"https://ex.com/{i}" for i in range(5)]
    fake = _mapping_fetch({"https://ex.com/sitemap.xml": _resp(_urlset(*locs))})
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", fake)

    assert fetch_sitemap_urls("https://ex.com", max_urls=3) == locs[:3]


def test_max_urls_caps_across_index_children(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cap bounds total work: c1 fills to the limit, so c2 is never fetched.
    mapping = {
        "https://ex.com/sitemap.xml": _resp(
            _index("https://ex.com/c1.xml", "https://ex.com/c2.xml")
        ),
        "https://ex.com/c1.xml": _resp(
            _urlset("https://ex.com/a", "https://ex.com/b"), url="https://ex.com/c1.xml"
        ),
        "https://ex.com/c2.xml": _resp(_urlset("https://ex.com/c"), url="https://ex.com/c2.xml"),
    }
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", _mapping_fetch(mapping))

    assert fetch_sitemap_urls("https://ex.com", max_urls=2) == [
        "https://ex.com/a",
        "https://ex.com/b",
    ]


def test_missing_sitemap_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", _mapping_fetch({}))

    assert fetch_sitemap_urls("https://ex.com") == []


def test_malformed_xml_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _mapping_fetch({"https://ex.com/sitemap.xml": _resp(b"<not-xml <<< &")})
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", fake)

    assert fetch_sitemap_urls("https://ex.com") == []


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "10.0.0.1"])
def test_ssrf_blocks_internal_initial_domain(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", _mapping_fetch({}))

    with pytest.raises(ValueError, match="SSRF"):
        fetch_sitemap_urls(f"http://{host}")


def test_ssrf_blocks_internal_child_sitemap(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {"https://ex.com/sitemap.xml": _resp(_index("http://169.254.169.254/child.xml"))}
    monkeypatch.setattr("polyfetch_scrape.utils.sitemap.fetch", _mapping_fetch(mapping))

    with pytest.raises(ValueError, match="SSRF"):
        fetch_sitemap_urls("https://ex.com")


@respx.mock
def test_respx_integration_real_fetch_chain() -> None:
    respx.get("https://ex.com/sitemap.xml").mock(
        return_value=httpx.Response(
            200, content=_urlset("https://ex.com/x"), headers={"content-type": "application/xml"}
        )
    )

    assert fetch_sitemap_urls("https://ex.com") == ["https://ex.com/x"]
