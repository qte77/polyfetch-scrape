"""Orchestrator: fetch each seed x path through the public fetch() and run detectors.

Named ``orchestrator`` (not ``hunt``) so the module name never collides with the
public ``hunt`` function re-exported on the package.

Security: the shared SSRF guard is **escalation-only** (:mod:`polyfetch_scrape.utils._ssrf`).
Each seed is trusted outright — a literal internal IP or ``localhost`` seed is never
blocked, so a caller can point ``hunt()`` at a local dev server. Only when a seed is
external does a URL derived from it (a path, a redirect target) get checked; an
internal seed means everything reachable from it is trusted too.

**Not yet pinned (#240).** Unlike ``utils.sitemap``/``utils.discovery`` (migrated to
``utils._ssrf.guarded_fetch``, which pins + re-checks every hop), ``_safe_fetch`` still
calls the bare ``fetch()`` with no ``max_tier``, so the full ``httpx`` → ``curl_cffi`` →
``patchright`` chain stays active — ``guarded_fetch`` cannot reach the ``patchright``
tier as designed (no per-hop pinning primitive there), so capping ``hunt()`` at
``curl_cffi`` to use it would silently remove its ability to detect JS-rendered content
on a fingerprint-blocked external seed. DNS rebinding therefore remains out of scope
here, and a redirect is still checked post-hoc via ``check_redirect`` rather than
pinned per hop, pending an explicit owner decision on #240: either accept that
residual gap (an attacker-triggered fingerprint block can escalate ``hunt()`` straight
to the unpinned ``patchright`` tier) or cap ``max_tier="curl_cffi"`` here too and lose
that capability. See ``utils/_ssrf.py`` for the guard this module still uses directly.
"""

from collections.abc import Iterable
from urllib.parse import urljoin

from polyfetch_scrape.client import fetch
from polyfetch_scrape.contrib.easter_hunt.detectors import DETECTORS, Detector
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import check_redirect, check_ssrf, is_seed_internal


def _safe_fetch(url: str, *, timeout: float, seed_is_internal: bool) -> Response | None:
    """Fetch one URL, swallowing FetchError (incl. FingerprintBlock) so a scan continues.

    A redirect escalating from an external seed onto an internal address raises
    ValueError through this swallow — a blocked target must stop the scan, not be
    silently skipped. No-op when the seed is internal (see the module docstring).
    """
    try:
        response = fetch(url, timeout=timeout)
    except FetchError:
        return None
    check_redirect(url, response, seed_is_internal=seed_is_internal)
    return response


def hunt(
    seeds: Iterable[str],
    *,
    paths: Iterable[str] = ("/",),
    detectors: Iterable[Detector] = DETECTORS,
    timeout: float = 10.0,
) -> list[Finding]:
    """Scan every seed x path with each detector, returning aggregated Findings.

    Materialise ``paths``/``detectors`` once so single-use iterables survive every
    seed. Each seed is its own trusted seed (see the module docstring) — computed
    once per seed and reused for every path, rather than re-resolved per URL. A
    blocked address (only possible when the seed is external) raises ValueError
    (not swallowed); a per-URL fetch failure is swallowed and the scan moves on.
    """
    path_list = tuple(paths)
    detector_list = tuple(detectors)
    findings: list[Finding] = []
    for seed in seeds:
        seed_internal = is_seed_internal(seed)
        for path in path_list:
            url = urljoin(seed, path)
            check_ssrf(url, seed_is_internal=seed_internal)
            response = _safe_fetch(url, timeout=timeout, seed_is_internal=seed_internal)
            if response is None:
                continue
            for detector in detector_list:
                findings.extend(detector(response))
    return findings
