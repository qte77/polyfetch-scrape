from collections.abc import Callable, Mapping

import httpx
import pytest
import respx

from polyfetch_scrape.errors import GoneError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils.discovery import discover

_HTML_SHELL = b"<!doctype html><html><head></head><body>app</body></html>"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None)


def _resp(body: bytes | str, *, url: str = "https://ex.com/", ct: str = "text/plain") -> Response:
    raw = body if isinstance(body, bytes) else body.encode()
    return Response(url=url, status=200, headers={}, body=raw, content_type=ct, backend="httpx")


def _mapping_fetch(mapping: Mapping[str, Response]) -> Callable[..., Response]:
    def _fetch(url: str, **_kwargs: object) -> Response:
        if url in mapping:
            return mapping[url]
        raise GoneError(f"terminal HTTP 404: {url}", status=404)

    return _fetch


def _patch(monkeypatch: pytest.MonkeyPatch, mapping: Mapping[str, Response]) -> None:
    monkeypatch.setattr("polyfetch_scrape.utils.discovery.fetch", _mapping_fetch(mapping))


def test_robots_sitemap_lines_split_by_event(monkeypatch: pytest.MonkeyPatch) -> None:
    robots = "User-agent: *\nSitemap: https://ex.com/sitemap.xml\nSitemap: https://ex.com/event-sitemap.xml\n"
    _patch(monkeypatch, {"https://ex.com/robots.txt": _resp(robots)})

    got = discover("https://ex.com")

    assert got.sitemaps == ("https://ex.com/sitemap.xml",)
    assert got.event_sitemaps == ("https://ex.com/event-sitemap.xml",)


def test_common_sitemap_probe_confirmed_and_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = b'<?xml version="1.0"?><urlset></urlset>'
    _patch(
        monkeypatch,
        {
            # declared in robots AND present on disk → must not double-count
            "https://ex.com/robots.txt": _resp("Sitemap: https://ex.com/sitemap.xml"),
            "https://ex.com/sitemap.xml": _resp(xml, ct="application/xml"),
            "https://ex.com/event-sitemap.xml": _resp(xml, ct="application/xml"),
        },
    )

    got = discover("https://ex.com")

    assert got.sitemaps == ("https://ex.com/sitemap.xml",)
    assert got.event_sitemaps == ("https://ex.com/event-sitemap.xml",)


def test_soft_404_html_shell_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    # SPA returns a 200 HTML shell for EVERY path — nothing structured really exists.
    shell = _resp(_HTML_SHELL, ct="text/html")

    def _always_shell(url: str, **_kwargs: object) -> Response:
        return _resp(_HTML_SHELL, url=url, ct="text/html")

    monkeypatch.setattr("polyfetch_scrape.utils.discovery.fetch", _always_shell)
    _ = shell

    got = discover("https://ex.com")

    assert got.sitemaps == ()
    assert got.event_sitemaps == ()
    assert got.llms_txt == ()


def test_llms_txt_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {"https://ex.com/llms.txt": _resp("# ex.com\n- /docs", ct="text/plain")})

    assert discover("https://ex.com").llms_txt == ("https://ex.com/llms.txt",)


def test_feeds_from_link_alternate_resolved_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        '<link rel="alternate" type="application/atom+xml" href="https://ex.com/atom">'
        "<link rel='alternate' type='text/calendar' href='/cal.ics'>"
        '<link rel="stylesheet" href="/style.css">'
    )
    _patch(monkeypatch, {"https://ex.com": _resp(html, ct="text/html")})

    assert discover("https://ex.com").feeds == (
        "https://ex.com/feed.xml",
        "https://ex.com/atom",
        "https://ex.com/cal.ics",
    )


def test_json_ld_types_collected_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        '<script type="application/ld+json">{"@type": "Event"}</script>'
        '<script type="application/ld+json">[{"@type": "Organization"},'
        '{"@type": ["WebSite", "Thing"]}]</script>'
        '<script type="application/ld+json">{"@graph": [{"@type": "BreadcrumbList"},'
        '{"@type": "Event"}]}</script>'
        '<script type="application/ld+json">not-json {{</script>'
    )
    _patch(monkeypatch, {"https://ex.com": _resp(html, ct="text/html")})

    assert discover("https://ex.com").json_ld_types == (
        "Event",
        "Organization",
        "WebSite",
        "Thing",
        "BreadcrumbList",
    )


def test_nothing_found_returns_empty_but_keeps_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, {})

    got = discover("https://ex.com")

    assert got.url == "https://ex.com"
    assert (got.sitemaps, got.event_sitemaps, got.feeds, got.llms_txt, got.json_ld_types) == (
        (),
        (),
        (),
        (),
        (),
    )


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "10.0.0.1"])
def test_ssrf_blocks_internal_origin(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    _patch(monkeypatch, {})

    with pytest.raises(ValueError, match="SSRF"):
        discover(f"http://{host}")


@respx.mock
def test_respx_integration_reads_robots_sitemap() -> None:
    respx.get("https://ex.com/robots.txt").mock(
        return_value=httpx.Response(
            200,
            content=b"Sitemap: https://ex.com/sitemap.xml\n",
            headers={"content-type": "text/plain"},
        )
    )
    respx.route().mock(return_value=httpx.Response(404))  # every other probe absent

    assert discover("https://ex.com").sitemaps == ("https://ex.com/sitemap.xml",)
