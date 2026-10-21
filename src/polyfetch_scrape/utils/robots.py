"""Opt-in robots.txt compliance helper, purely at the fetch layer (#147).

Given a URL and a user-agent, :func:`is_allowed` fetches and parses the origin's
``/robots.txt`` and reports whether that user-agent may fetch the URL. The allow/deny
logic itself is the stdlib :mod:`urllib.robotparser` — no hand-rolled parsing — but this
module implements two RFC 9309 ("Robots Exclusion Protocol",
https://www.rfc-editor.org/rfc/rfc9309) rules explicitly rather than leaning on whatever
:mod:`urllib.robotparser` version happens to be installed:

- **Section 2.2.2 ("The 'Allow' and 'Disallow' Lines")**: "The /robots.txt URI is
  implicitly allowed." Checked before any fetch/parse (:func:`is_allowed` short-circuits
  on the path), so the result does not depend on which Python 3.11-3.14 patch release's
  ``urllib.robotparser.RobotFileParser.can_fetch`` happens to special-case this (verified
  directly against the installed stdlib: Python 3.14's ``robotparser.py`` checks
  ``url == '/robots.txt'`` and returns ``True``; Python 3.12's does not — see the
  ``fix(tests)`` commit this module's test file references).
- **Section 2.3.1.3 ("Unavailable" Status, HTTP 4xx incl. 404)**: "the crawler MAY access
  any resources on the server" — :func:`is_allowed` returns ``True``.
- **Section 2.3.1.4 ("Unreachable" Status, HTTP 5xx, or a network/transport failure with
  no HTTP response at all)**: "the robots.txt file is undefined and the crawler MUST
  assume complete disallow" — :func:`is_allowed` returns ``False``. (The RFC also allows
  falling back to a stale cached copy after a long unreachable period; this module has no
  cache, so every call that hits this branch disallows.)

Scope: **opt-in and dual-use**, like the rest of ``utils/``. Neither
:func:`polyfetch_scrape.fetch` nor :func:`polyfetch_scrape.utils.discovery.discover`
calls this automatically — a caller that wants robots.txt enforcement calls
:func:`is_allowed` itself (#147, cross-linked with the structured-first tracker #153 and
discovery's own #135).

Security: reuses :mod:`polyfetch_scrape.utils.discovery`'s ``/robots.txt`` fetch
(``fetch_robots_txt_status``), which carries the same escalation-only SSRF guard
(:mod:`polyfetch_scrape.utils._ssrf`) as ``discover()`` — ``url`` itself (the seed) is
never blocked; only the derived ``/robots.txt`` fetch is checked, and only when the seed
is external. :func:`is_allowed` can therefore raise ``ValueError`` the same way
``discover()`` does, for the same reason.

Not reproduced: RFC 9309 doesn't define a status for an HTML soft-404 (a ``200`` SPA
shell where ``/robots.txt`` doesn't really exist) — that's this codebase's own
soft-404 guard, not an RFC status. It reports its real (non-5xx) status with no text,
so it falls through to the section 2.3.1.3 "allow" branch — the same outcome as if the
site genuinely had no robots.txt.
"""

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from polyfetch_scrape.utils._ssrf import is_seed_internal
from polyfetch_scrape.utils.discovery import fetch_robots_txt_status

_ROBOTS_TXT_PATH = "/robots.txt"
_UNREACHABLE_STATUS = 500  # RFC 9309 §2.3.1.4: 5xx (or no status at all) → disallow


def is_allowed(url: str, user_agent: str = "*") -> bool:
    """True if ``user_agent`` may fetch ``url`` per its origin's ``/robots.txt``.

    ``url`` is the seed — never blocked by the SSRF guard itself (see the module
    docstring); a literal internal IP or ``localhost`` is fine, for pointing this at a
    local dev server. ``url`` itself being ``/robots.txt`` is always allowed (RFC 9309
    §2.2.2, checked before any fetch). Otherwise: a 4xx (incl. 404) or absent robots.txt
    allows everything (§2.3.1.3); a 5xx, or no HTTP response at all, disallows everything
    (§2.3.1.4) — see the module docstring. Raises ``ValueError`` if the derived
    ``/robots.txt`` fetch resolves to, or redirects to, an internal address while the
    seed is external (SSRF guard — escalation-only, see ``utils/_ssrf.py``).
    """
    target = url if "://" in url else f"https://{url}"
    if urlsplit(target).path == _ROBOTS_TXT_PATH:
        return True  # RFC 9309 §2.2.2
    result = fetch_robots_txt_status(_origin(target), is_seed_internal(target))
    if result.text is None:
        return not _is_unreachable(result.status)
    parser = RobotFileParser()
    parser.parse(result.text.splitlines())
    return parser.can_fetch(user_agent, target)


def _is_unreachable(status: int | None) -> bool:
    """RFC 9309 §2.3.1.4: ``True`` for a 5xx response, or no response at all (``status`` is
    ``None`` — a transport/network failure). ``False`` (§2.3.1.3, any other failure incl.
    4xx/404) means the crawler MAY access everything.
    """
    return status is None or status >= _UNREACHABLE_STATUS


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
