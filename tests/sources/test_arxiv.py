from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.sources import arxiv
from polyfetch_scrape.sources.arxiv import (
    ArxivNotFoundError,
    ArxivPaper,
    ArxivParseError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_2301.00001.xml"


def _ok_response(body: bytes, *, url: str = "https://export.arxiv.org/api/query") -> Response:
    return Response(
        url=url,
        status=200,
        headers={"content-type": "application/atom+xml"},
        body=body,
        content_type="application/atom+xml",
        backend="httpx",
    )


# --- ArxivPaper dataclass ---


def test_arxivpaper_holds_fields() -> None:
    paper = ArxivPaper(
        arxiv_id="2301.00001",
        title="NFTrig",
        authors=("A", "B"),
        abstract="x",
        categories=("cs.HC",),
        pdf_url="https://arxiv.org/pdf/2301.00001v1",
        abs_url="https://arxiv.org/abs/2301.00001v1",
        published_at="2022-12-21T18:07:06Z",
        updated_at="2022-12-21T18:07:06Z",
    )
    assert paper.arxiv_id == "2301.00001"
    assert isinstance(paper.authors, tuple)
    assert isinstance(paper.categories, tuple)


def test_arxivpaper_is_frozen() -> None:
    paper = ArxivPaper(
        arxiv_id="x",
        title="x",
        authors=(),
        abstract="",
        categories=(),
        pdf_url="",
        abs_url="",
        published_at="",
        updated_at="",
    )
    with pytest.raises(FrozenInstanceError):
        paper.title = "mut"  # type: ignore[misc]


# --- _parse_entry ---


def test_parse_entry_extracts_all_fields_from_golden_fixture() -> None:
    paper = arxiv._parse_entry(FIXTURE.read_bytes())

    assert paper.arxiv_id == "2301.00001v1"
    assert paper.title == "NFTrig"
    assert paper.authors == (
        "Jordan Thompson",
        "Ryan Benac",
        "Kidus Olana",
        "Talha Hassan",
        "Andrew Sward",
        "Tauheed Khan Mohd",
    )
    assert "NFTrig is a web-based application" in paper.abstract
    assert paper.categories == ("cs.HC",)
    assert paper.pdf_url == "https://arxiv.org/pdf/2301.00001v1"
    assert paper.abs_url == "https://arxiv.org/abs/2301.00001v1"
    assert paper.published_at == "2022-12-21T18:07:06Z"
    assert paper.updated_at == "2022-12-21T18:07:06Z"


def test_parse_entry_raises_not_found_on_empty_feed() -> None:
    empty = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:totalResults>
</feed>"""
    with pytest.raises(ArxivNotFoundError):
        arxiv._parse_entry(empty)


def test_parse_entry_raises_parse_error_on_malformed_xml() -> None:
    with pytest.raises(ArxivParseError):
        arxiv._parse_entry(b"<not-xml-at-all")


# --- get() ---


def test_get_returns_arxivpaper_using_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    body = FIXTURE.read_bytes()
    captured: dict[str, str] = {}

    def fake_fetch(url: str, **_kw: object) -> Response:
        captured["url"] = url
        return _ok_response(body)

    monkeypatch.setattr("polyfetch_scrape.sources.arxiv.fetch", fake_fetch)

    paper = arxiv.get("2301.00001")

    assert paper.title == "NFTrig"
    assert "id_list=2301.00001" in captured["url"]
    assert captured["url"].startswith("https://export.arxiv.org/api/query")


def test_get_propagates_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_kw: object) -> Response:
        raise FetchError("network down")

    monkeypatch.setattr("polyfetch_scrape.sources.arxiv.fetch", boom)

    with pytest.raises(FetchError):
        arxiv.get("2301.00001")


def test_get_raises_not_found_on_empty_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""

    def fake_fetch(*_a: object, **_kw: object) -> Response:
        return _ok_response(empty)

    monkeypatch.setattr("polyfetch_scrape.sources.arxiv.fetch", fake_fetch)

    with pytest.raises(ArxivNotFoundError):
        arxiv.get("9999.99999")
