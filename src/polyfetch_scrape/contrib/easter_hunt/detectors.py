"""Page-artifact detectors for easter_hunt.

Each detector is a pure function: it takes an already-fetched ``Response`` and
returns a list of ``Finding`` objects, never performing I/O.

Header limitation: ``Response.headers`` is ``Mapping[str, str]`` with
last-write-wins collapse of duplicate header names, so ``weird_headers`` sees
only the final value of a repeated header and cannot flag per-value anomalies
in multi-valued headers (e.g. multiple ``Set-Cookie``).
"""

import re
from collections.abc import Callable
from typing import Final
from urllib.parse import urlparse

from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.response import Response

Detector = Callable[[Response], list[Finding]]

# Lazy capture with a fixed right-anchor "-->"; an unterminated comment yields no
# match (silently dropped). NOT linear: the engine restarts a scan from every
# unmatched "<!--", so a body full of unclosed comment-opens is O(k*n). Bodies are
# therefore capped at _MAX_SCAN_BYTES (see _decode_body) to bound worst-case work.
_MAX_SCAN_BYTES: Final = 512 * 1024
_COMMENT_RE: Final = re.compile(r"<!--([\s\S]*?)-->", re.MULTILINE)

_BOX_CHARS: Final[frozenset[str]] = frozenset("▄▓█▀╓╙")
_RECRUITING_STEMS: Final[tuple[str, ...]] = ("hir", "join", "recruit", "career")
# Stripped, lower-cased prefixes of GTM / gtag boilerplate we never report. Kept
# specific on purpose: generic stems like "begin "/"end " would suppress legitimate
# recruiting comments such as "<!-- Begin your career at Acme -->".
_GTM_PREFIXES: Final[tuple[str, ...]] = (
    "google tag manager",
    "end google tag manager",
    "global site tag",
    "gtm ",
)
_SNIPPET_MAX: Final = 120
_NOVELTY_MIN_CONFIDENCE: Final = 0.1

# Strip C0/C1 control characters (incl. ANSI escape \x1b) so a snippet built from
# untrusted page/header bytes cannot inject terminal escape sequences when printed.
_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _decode_body(body: bytes) -> str:
    """Decode a response body, capped to bound worst-case scan/regex work."""
    return body[:_MAX_SCAN_BYTES].decode("utf-8", errors="replace")


def _snippet(text: str) -> str:
    """Length-capped, terminal-safe excerpt: drop control chars, then truncate."""
    return _CONTROL_RE.sub("", text)[:_SNIPPET_MAX]


def _suppressed(comment: str) -> bool:
    stripped = comment.strip()
    if stripped.startswith("[if "):  # IE conditional, e.g. <!--[if lt IE 9]>
        return True
    return stripped.lower().startswith(_GTM_PREFIXES)


def _novelty_confidence(comment: str) -> float:
    box = sum(1 for ch in comment if ch in _BOX_CHARS)
    density = box / max(len(comment), 1)
    return min(1.0, density * 8.0)


def html_comments(response: Response) -> list[Finding]:
    """Flag HTML comments that look like recruiting hints or ASCII-art easter eggs."""
    text = _decode_body(response.body)
    findings: list[Finding] = []
    for index, match in enumerate(_COMMENT_RE.finditer(text)):
        comment = match.group(1)
        if _suppressed(comment):
            continue
        location = f"body:comment[{index}]"
        snippet = _snippet(comment.strip())
        if any(stem in comment.lower() for stem in _RECRUITING_STEMS):
            findings.append(
                Finding(
                    "html_comments", "recruiting", "notable", location, snippet, 0.9, response.url
                )
            )
            continue
        confidence = _novelty_confidence(comment)
        if confidence >= _NOVELTY_MIN_CONFIDENCE:
            findings.append(
                Finding(
                    "html_comments", "novelty", "info", location, snippet, confidence, response.url
                )
            )
    return findings


# Curated known-weird headers -> (category, severity, confidence). This table IS the
# allowlist: any header not present yields no Finding (precision over recall). A
# wildcard "emit anything unusual" rule would drown the operator in CDN/app noise.
_WEIRD_HEADERS: Final[dict[str, tuple[str, str, float]]] = {
    "p3p": ("policy", "notable", 0.95),
    "x-clacks-overhead": ("novelty", "info", 1.0),
    "x-hire-me": ("recruiting", "notable", 0.9),
    "x-recruitment": ("recruiting", "notable", 0.9),
    "x-powered-by": ("stack", "info", 0.9),
    "x-aspnet-version": ("stack", "info", 0.95),
    "x-generator": ("stack", "info", 0.85),
    "x-drupal-cache": ("stack", "info", 0.95),
    "x-request-id": ("stack", "info", 0.6),
    "x-debug-token": ("exposure", "warn", 0.95),
    "x-debug-token-link": ("exposure", "warn", 0.95),
}


def weird_headers(response: Response) -> list[Finding]:
    """Flag unusual HTTP response headers (privacy tokens, stack leaks, easter eggs).

    Keys in ``Response.headers`` are already lowercased by the backend, so the
    table is matched against them directly.
    """
    findings: list[Finding] = []
    for key, value in response.headers.items():
        entry = _WEIRD_HEADERS.get(key)
        if entry is None:
            continue
        category, severity, confidence = entry
        snippet = _snippet(f"{key}: {value}")
        findings.append(
            Finding(
                "weird_headers",
                category,
                severity,
                f"header:{key}",
                snippet,
                confidence,
                response.url,
            )
        )
    return findings


# Well-known path -> (category, severity). "/404-not-a-real-page" is deliberately
# absent: it is a negative-control probe that must never classify as present.
_WELL_KNOWN: Final[dict[str, tuple[str, str]]] = {
    "/humans.txt": ("stack", "info"),
    "/robots.txt": ("policy", "info"),
    "/ads.txt": ("policy", "info"),
    "/security.txt": ("policy", "info"),
    "/.well-known/security.txt": ("policy", "info"),
    "/.well-known/dnt-policy.txt": ("policy", "info"),
    "/.well-known/change-password": ("policy", "info"),
    "/.well-known/gpc.json": ("policy", "info"),
    "/sitemap.xml": ("stack", "info"),
    "/manifest.json": ("stack", "info"),
    "/.git/HEAD": ("exposure", "warn"),
    "/.env": ("exposure", "warn"),
}

_GIT_HEAD_RE: Final = re.compile(r"ref:\s+refs/", re.IGNORECASE)
_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_DOTENV_RE: Final = re.compile(r"(?m)^[A-Z_][A-Z0-9_]*=\S")


def _exposure_confirmed(path: str, body: str) -> bool:
    """Reject 200 soft-404 / SPA-shell bodies so we never raise a false exposure."""
    if path == "/.git/HEAD":
        head = body.strip()
        return bool(_GIT_HEAD_RE.match(head) or _GIT_SHA_RE.match(head))
    if path == "/.env":
        return bool(_DOTENV_RE.search(body))
    return False  # pragma: no cover - defensive fallback for unhandled exposure paths


def wellknown_present(response: Response) -> list[Finding]:
    """Classify a fetched well-known path as present, gating exposures on a body sniff."""
    if response.status != 200:
        return []
    path = urlparse(response.url).path
    entry = _WELL_KNOWN.get(path)
    if entry is None:
        return []
    category, severity = entry
    body = _decode_body(response.body)
    if category == "exposure":
        if not _exposure_confirmed(path, body):
            return []
        confidence = 0.9
    else:
        confidence = 1.0
    snippet = _snippet(body.strip())
    location = f"path:{path}"
    return [
        Finding(
            "wellknown_present", category, severity, location, snippet, confidence, response.url
        )
    ]


# Default detector pack. wellknown_present only fires for well-known paths, so it is
# harmless on a "/" sweep and meaningful once paths include WELL_KNOWN_PATHS.
DETECTORS: tuple[Detector, ...] = (html_comments, weird_headers, wellknown_present)
