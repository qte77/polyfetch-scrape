"""Browser-shape User-Agent string pool for the httpx tier.

Some endpoints treat ``python-httpx/...`` (the httpx default UA) as a bot
signature on first sight. Sending a current desktop-browser ``User-Agent``
blends the egress with regular visitor traffic and keeps the cheap
``httpx`` tier viable before the orchestrator falls through to
``curl_cffi`` (which solves a different problem — TLS fingerprint).

Refresh :data:`USER_AGENTS` quarterly from https://useragents.me/ — pick
top entries from the "Most common desktop user-agents" table. Background on
choosing UAs: https://hasdata.com/blog/user-agents-for-web-scraping

To confirm which UA actually leaves the wire, fetch a header-echo endpoint and
print the body: ``polyfetch fetch https://httpbin.org/user-agent --show-body``
(also ``https://postman-echo.com/headers`` for all headers, or
``https://ifconfig.me/ua`` for the bare UA).

Generalized port of ``qte77/scrape-stock-kpi/src/utils/http_ua.py``,
inlined here (no pydantic-settings dependency). The ``require_https``
guard from that module is intentionally not ported: this project's
``fetch()`` contract is "fetch a URL", not "fetch an https URL only".
"""

import random
from typing import Protocol

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.10 Safari/605.1.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36",
)

STABLE_USER_AGENT: str = USER_AGENTS[0]


class _RngLike(Protocol):
    def choice(self, seq: tuple[str, ...]) -> str: ...


def pick_user_agent(rng: _RngLike | None = None) -> str:
    """Return a randomly-chosen User-Agent from :data:`USER_AGENTS`.

    Pass a seeded :class:`random.Random` (or any duck-typed object with
    a compatible ``choice`` method) for deterministic tests; omit for
    the module-level ``random`` instance.
    """
    chooser: _RngLike = rng if rng is not None else random
    return chooser.choice(USER_AGENTS)
