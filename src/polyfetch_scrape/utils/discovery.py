"""Discover the structured entrypoints a site exposes, purely at the fetch layer.

Given a URL/origin, :func:`discover` reports which cheaper-than-HTML entrypoints a
site advertises — sitemaps (incl. event variants), RSS/Atom/iCal feeds, ``llms.txt``,
and embedded JSON-LD ``@type`` values — so a downstream consumer can parse structured
data instead of LLM-scraping HTML.

Scope: this **stays at the transport-layer boundary** — it returns entrypoint
URLs/types only and never parses or extracts the content behind them (that remains a
downstream concern, per the README/architecture invariants).

Security: every fetched URL passes through the shared literal-IP SSRF guard first
(:func:`polyfetch_scrape.utils._ssrf.check_ssrf`). Soft-404s are rejected — a site that
returns a ``200`` HTML shell for every path (SPA) must not read as "``/llms.txt``
present", so probes sniff the content-type/body before counting an entrypoint.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from polyfetch_scrape.client import fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import check_ssrf

# Arbitrary parsed JSON (``json.loads`` output). A recursive alias lets pyright-strict
# narrow ``isinstance`` branches within the union — no ``Any`` and no casts needed.
Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]

_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/event-sitemap.xml", "/events-sitemap.xml")
_LLMS_PATHS = ("/llms.txt", "/llms-full.txt")
_FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "text/calendar"})

_SITEMAP_LINE_RE = re.compile(r"(?im)^\s*Sitemap:\s*(\S+)")
_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w-]+)\s*=\s*(["'])(.*?)\2""")
_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_XML_PREFIXES = ("<?xml", "<urlset", "<sitemapindex")
_HTML_MARKERS = ("<!doctype html", "<html")


@dataclass(frozen=True, slots=True)
class DiscoveredSources:
    """Structured entrypoints discovered for ``url`` (empty tuples when none found)."""

    url: str
    sitemaps: tuple[str, ...] = ()
    event_sitemaps: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    llms_txt: tuple[str, ...] = ()
    json_ld_types: tuple[str, ...] = ()


def discover(url: str) -> DiscoveredSources:
    """Report the structured entrypoints ``url``'s site advertises (never raises for absence).

    Returns empty tuples for sources the site does not expose. Raises ``ValueError`` if
    ``url`` (or a probed path) resolves to a literal internal IP (SSRF guard).
    """
    target = url if "://" in url else f"https://{url}"
    origin = _origin(target)
    check_ssrf(origin)

    sitemaps, event_sitemaps = _discover_sitemaps(origin)
    html = _page_html(target)
    return DiscoveredSources(
        url=url,
        sitemaps=tuple(sitemaps),
        event_sitemaps=tuple(event_sitemaps),
        feeds=tuple(_feeds(target, html)),
        llms_txt=tuple(_llms_txt(origin)),
        json_ld_types=tuple(_json_ld_types(html)),
    )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _fetch(url: str) -> Response | None:
    """Fetch ``url`` (structured sources never need JS); None on 404 / fetch failure."""
    check_ssrf(url)
    try:
        return fetch(url, max_tier="curl_cffi")
    except FetchError:
        return None  # absent source — same swallow-to-None convention as utils.sitemap


def _head(body: bytes, size: int = 512) -> str:
    return body[:size].decode("utf-8", "replace").lstrip().lower()


def _looks_like_xml(resp: Response) -> bool:
    if "xml" in (resp.content_type or "").lower():
        return True
    return _head(resp.body).startswith(_XML_PREFIXES)


def _looks_like_html(resp: Response) -> bool:
    if "html" in (resp.content_type or "").lower():
        return True
    return _head(resp.body).startswith(_HTML_MARKERS)


def _discover_sitemaps(origin: str) -> tuple[list[str], list[str]]:
    """Sitemap entrypoints from robots.txt ``Sitemap:`` lines + confirmed common paths."""
    found = list(_robots_sitemaps(origin))
    for path in _SITEMAP_PATHS:
        url = f"{origin}{path}"
        resp = _fetch(url)
        if resp is not None and _looks_like_xml(resp):
            found.append(url)
    return _split_events(found)


def _robots_sitemaps(origin: str) -> list[str]:
    resp = _fetch(f"{origin}/robots.txt")
    if resp is None or _looks_like_html(resp):  # HTML soft-404 → no robots.txt
        return []
    return _SITEMAP_LINE_RE.findall(resp.body.decode("utf-8", "replace"))


def _split_events(urls: list[str]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    event: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        (event if "event" in urlsplit(u).path.lower() else plain).append(u)
    return plain, event


def _page_html(url: str) -> str:
    resp = _fetch(url)
    return (
        resp.body.decode("utf-8", "replace") if resp is not None and _looks_like_html(resp) else ""
    )


def _feeds(base_url: str, html: str) -> list[str]:
    """RSS/Atom/iCal hrefs from ``<link rel="alternate" type=...>`` tags (resolved absolute)."""
    feeds: list[str] = []
    seen: set[str] = set()
    for tag in _LINK_TAG_RE.findall(html):
        attrs = {m.group(1).lower(): m.group(3) for m in _ATTR_RE.finditer(tag)}
        if attrs.get("rel", "").lower() != "alternate":
            continue
        if attrs.get("type", "").lower() not in _FEED_TYPES or "href" not in attrs:
            continue
        href = urljoin(base_url, attrs["href"])
        if href not in seen:
            seen.add(href)
            feeds.append(href)
    return feeds


def _llms_txt(origin: str) -> list[str]:
    found: list[str] = []
    for path in _LLMS_PATHS:
        url = f"{origin}{path}"
        resp = _fetch(url)
        if resp is not None and not _looks_like_html(resp):  # reject 200 HTML SPA shell
            found.append(url)
    return found


def _json_ld_types(html: str) -> list[str]:
    types: list[str] = []
    seen: set[str] = set()
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue  # malformed JSON-LD block → skip
        for t in _types_in(data):
            if t not in seen:
                seen.add(t)
                types.append(t)
    return types


def _types_in(data: Json) -> list[str]:
    """Collect ``@type`` strings from a JSON-LD value (handles lists and ``@graph`` nesting).

    Unexpected shapes yield no types rather than raising (best-effort extraction).
    """
    if isinstance(data, list):
        return _types_in_list(data)
    if not isinstance(data, dict):
        return []
    out = _type_values(data.get("@type"))
    out.extend(_types_in_list(data.get("@graph")))
    return out


def _types_in_list(value: Json) -> list[str]:
    """Flatten :func:`_types_in` over a JSON-LD list value (non-list → no types)."""
    if not isinstance(value, list):
        return []
    return [t for item in value for t in _types_in(item)]


def _type_values(raw: Json) -> list[str]:
    """The ``@type`` string(s) from a raw ``@type`` value (a str or a list of str)."""
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, str)]
    return []
