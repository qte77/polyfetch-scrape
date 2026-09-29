"""Suite-wide fixtures.

The shared SSRF guard (``utils._ssrf.check_ssrf``) resolves hostnames via
``socket.getaddrinfo`` before allowing a guarded fetch — ``discover()``,
``fetch_sitemap_urls()``, and the ``easter_hunt`` contrib's ``hunt()`` all call
it (#181) — so, unstubbed, every test that drives one of those would perform a
real DNS lookup. CONTRIBUTING.md requires ``make test`` to stay network-free.

Pin the resolver seam at the socket boundary to a fixed public answer: every
host the suite exercises resolves to the same address unless a test overrides
this fixture's monkeypatch with its own (applied later in the same test, so it
wins).

NOT an RFC 5737 documentation address (192.0.2.0/24 "TEST-NET-1",
198.51.100.0/24 "TEST-NET-2", 203.0.113.0/24 "TEST-NET-3"): verified empirically
that Python's :mod:`ipaddress` classifies all three ranges as ``is_private ==
True`` (they are reserved for documentation, not for public routing), so a
guard-under-test would reject the "public" stub address, which is backwards.
``93.184.216.34`` is the long-standing public address of example.com/.org —
the same address the rest of this suite (e.g. ``tests/utils/test_ssrf.py``,
``tests/contrib/easter_hunt/test_hunt.py``) already uses as "obviously public".
"""

import socket
from collections.abc import Sequence

import pytest

_GETADDRINFO = "polyfetch_scrape.utils._ssrf.socket.getaddrinfo"
_PUBLIC_ADDR = "93.184.216.34"  # long-standing public address of example.com/.org

_AddrInfo = tuple[int, int, int, str, tuple[str, int]]


def _stub_getaddrinfo(*_args: object, **_kwargs: object) -> Sequence[_AddrInfo]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_ADDR, 0))]


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_GETADDRINFO, _stub_getaddrinfo)
