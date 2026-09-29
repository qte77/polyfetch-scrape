"""Discover the URLs a site advertises via ``/sitemap.xml``.

Resolves a domain into the concrete URLs it publishes: fetches ``/sitemap.xml``
through the public :func:`fetch`, follows a ``<sitemapindex>`` one level into its
child sitemaps, transparently decompresses ``.xml.gz`` payloads, and parses the
(untrusted) XML with :mod:`defusedxml`.

Security: every fetched URL — the initial sitemap **and** each child sitemap URL
parsed from an index (attacker-controlled) — is passed through the shared SSRF
guard first, which resolves the hostname and rejects it if *any* answer is an
internal address; the URL a response actually landed on (or redirects to) is
re-checked before its body is parsed.
"""

import gzip
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring

from polyfetch_scrape.client import fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.utils._ssrf import check_redirect, check_ssrf

_GZIP_MAGIC = b"\x1f\x8b"


def fetch_sitemap_urls(domain: str, *, max_urls: int = 10_000) -> list[str]:
    """Return the URLs advertised by ``domain``'s ``/sitemap.xml`` (index-aware).

    Follows a ``<sitemapindex>`` one level into its child sitemaps. Returns ``[]``
    when the site has no sitemap (404 / fetch failure) or the payload is unparseable.
    Raises ``ValueError`` if any fetched URL — the address its host resolves to, or a
    redirect it lands on — is internal (SSRF guard).
    """
    urls: list[str] = []
    root = _fetch_and_parse(_sitemap_url(domain))
    if root is None:
        return urls
    if _localname(root.tag) == "sitemapindex":
        for child in _locs(root):
            child_root = _fetch_and_parse(child)
            if child_root is not None:
                _collect(child_root, urls, max_urls)
            if len(urls) >= max_urls:
                break
    else:
        _collect(root, urls, max_urls)
    return urls[:max_urls]


def _sitemap_url(domain: str) -> str:
    parts = urlsplit(domain if "://" in domain else f"https://{domain}")
    return f"{parts.scheme}://{parts.netloc}/sitemap.xml"


def _fetch_and_parse(url: str) -> Element | None:
    check_ssrf(url)
    try:
        resp = fetch(url, max_tier="curl_cffi")  # sitemaps never need JS
    except FetchError:
        return None  # 404 / retries exhausted → treat as "no sitemap"
    check_redirect(url, resp)  # a public host may have 30x-ed us onto an internal one
    body = gzip.decompress(resp.body) if resp.body[:2] == _GZIP_MAGIC else resp.body
    try:
        return fromstring(body)
    except ParseError:
        return None  # unparseable payload → skip this document


def _locs(root: Element) -> list[str]:
    return [el.text.strip() for el in root.iter() if _localname(el.tag) == "loc" and el.text]


def _collect(root: Element, urls: list[str], max_urls: int) -> None:
    for loc in _locs(root):
        if len(urls) >= max_urls:
            return
        urls.append(loc)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
