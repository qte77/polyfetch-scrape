"""Suite-wide fixtures.

The SSRF guard resolves hostnames before allowing a fetch (#181), so every test
that drives a guarded util (``discover``, ``fetch_sitemap_urls``, ``hunt``) would
otherwise perform real DNS — which `make test` forbids and which makes results
depend on the runner's resolver.

Pin the resolver seam to a deterministic table instead: every host the suite uses
reads as public unless it is a known internal alias. A test that cares about a
specific mapping overrides the same seam with its own ``monkeypatch.setattr``,
which is applied later and therefore wins.
"""

import pytest

_RESOLVER = "polyfetch_scrape.utils._ssrf._resolve"

# 93.184.216.34 — the long-standing public address of example.com; any external
# address works, it just has to be one the guard does not consider internal.
_PUBLIC = ("93.184.216.34",)
_INTERNAL_ALIASES = {"localhost": ("127.0.0.1",)}


def _stub_resolve(host: str) -> list[str]:
    return list(_INTERNAL_ALIASES.get(host, _PUBLIC))


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_RESOLVER, _stub_resolve)
