"""Opt-in robots.txt compliance helper, purely at the fetch layer (#147).

Given a URL and a user-agent, :func:`is_allowed` fetches and parses the origin's
``/robots.txt`` and reports whether that user-agent may fetch the URL. The allow/deny
logic itself is the stdlib :mod:`urllib.robotparser` (RFC 9309) — no hand-rolled
parsing.

Scope: **opt-in and dual-use**, like the rest of ``utils/``. Neither
:func:`polyfetch_scrape.fetch` nor :func:`polyfetch_scrape.utils.discovery.discover`
calls this automatically — a caller that wants robots.txt enforcement calls
:func:`is_allowed` itself (#147, cross-linked with the structured-first tracker #153 and
discovery's own #135).

Security: reuses :mod:`polyfetch_scrape.utils.discovery`'s ``/robots.txt`` fetch
(``fetch_robots_txt``), which carries the same escalation-only SSRF guard
(:mod:`polyfetch_scrape.utils._ssrf`) as ``discover()`` — ``url`` itself (the seed) is
never blocked; only the derived ``/robots.txt`` fetch is checked, and only when the seed
is external. :func:`is_allowed` can therefore raise ``ValueError`` the same way
``discover()`` does, for the same reason.

Simplification: a missing, unreachable, or unparseable robots.txt (any non-2xx, a
connection failure, or an HTML soft-404 shell) is treated as "allow everything" — the
same swallow-to-absence convention ``discover()`` and ``fetch_sitemap_urls`` already use
for a missing source. This does **not** reproduce RFC 9309 section 2.3.1.4's stricter
"treat 5xx / 401 / 403 as a full disallow": that distinction needs the fetch layer to
surface the status code on failure, which the shared ``_fetch`` helper's
swallow-to-``None`` currently does not. Revisit if a caller needs that nuance.
"""

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from polyfetch_scrape.utils._ssrf import is_seed_internal
from polyfetch_scrape.utils.discovery import fetch_robots_txt


def is_allowed(url: str, user_agent: str = "*") -> bool:
    """True if ``user_agent`` may fetch ``url`` per its origin's ``/robots.txt``.

    ``url`` is the seed — never blocked by the SSRF guard itself (see the module
    docstring); a literal internal IP or ``localhost`` is fine, for pointing this at a
    local dev server. A missing, unreachable, or unparseable robots.txt allows
    everything. Raises ``ValueError`` if the derived ``/robots.txt`` fetch resolves to,
    or redirects to, an internal address while the seed is external (SSRF guard —
    escalation-only, see ``utils/_ssrf.py``).
    """
    target = url if "://" in url else f"https://{url}"
    text = fetch_robots_txt(_origin(target), is_seed_internal(target))
    if text is None:
        return True  # no robots.txt (absent/unreachable/soft-404) — allow everything
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(user_agent, target)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
