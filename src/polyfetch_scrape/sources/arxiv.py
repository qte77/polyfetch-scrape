"""arXiv API wrapper.

Thin source-specific wrapper around `polyfetch_scrape.fetch()`. Calls the
arXiv export API and parses the Atom XML response into a typed dataclass.

Public surface: ArxivPaper, get(), ArxivError, ArxivNotFoundError, ArxivParseError.
"""

from dataclasses import dataclass
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from polyfetch_scrape.client import fetch
from polyfetch_scrape.errors import FetchError

ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivError(FetchError):
    """Base for arxiv-specific failures."""


class ArxivNotFoundError(ArxivError):
    """arXiv API returned no entry for the requested id."""


class ArxivParseError(ArxivError):
    """Atom response could not be parsed into ArxivPaper."""


@dataclass(frozen=True, slots=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    categories: tuple[str, ...]
    pdf_url: str
    abs_url: str
    published_at: str
    updated_at: str


def get(arxiv_id: str, *, timeout: float = 30.0) -> ArxivPaper:
    """Fetch an arXiv paper's metadata by id (e.g. ``2301.00001``)."""
    url = f"{ARXIV_API}?{urlencode({'id_list': arxiv_id})}"
    resp = fetch(url, timeout=timeout)
    return _parse_entry(resp.body)


def _parse_entry(xml_bytes: bytes) -> ArxivPaper:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ArxivParseError(f"could not parse arxiv response: {exc}") from exc

    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        raise ArxivNotFoundError("arxiv returned no entry for the requested id")

    try:
        return ArxivPaper(
            arxiv_id=_strip_arxiv_id(_text(entry, "id")),
            title=_text(entry, "title").strip(),
            authors=tuple(
                _text(a, "name") for a in entry.findall(f"{_ATOM_NS}author")
            ),
            abstract=_text(entry, "summary").strip(),
            categories=tuple(
                c.attrib["term"] for c in entry.findall(f"{_ATOM_NS}category")
            ),
            pdf_url=_link(entry, "pdf"),
            abs_url=_link(entry, "alternate"),
            published_at=_text(entry, "published"),
            updated_at=_text(entry, "updated"),
        )
    except (KeyError, AttributeError) as exc:
        raise ArxivParseError(f"missing expected field in arxiv entry: {exc}") from exc


def _text(parent: ET.Element, tag: str) -> str:
    el = parent.find(f"{_ATOM_NS}{tag}")
    if el is None or el.text is None:
        raise ArxivParseError(f"missing <{tag}> in arxiv entry")
    return el.text


def _link(entry: ET.Element, kind: str) -> str:
    """Return href of <link rel="alternate"/> or <link title="pdf"/>."""
    for link in entry.findall(f"{_ATOM_NS}link"):
        if kind == "pdf" and link.attrib.get("title") == "pdf":
            return link.attrib["href"]
        if kind == "alternate" and link.attrib.get("rel") == "alternate":
            return link.attrib["href"]
    raise ArxivParseError(f"no {kind} link in arxiv entry")


def _strip_arxiv_id(atom_id: str) -> str:
    """Convert 'http://arxiv.org/abs/2301.00001v1' → '2301.00001v1'."""
    return atom_id.rsplit("/", 1)[-1]
