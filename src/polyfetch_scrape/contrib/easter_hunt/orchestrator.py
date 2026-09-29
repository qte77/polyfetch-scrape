"""Orchestrator: fetch each seed x path through the public fetch() and run detectors.

Named ``orchestrator`` (not ``hunt``) so the module name never collides with the
public ``hunt`` function re-exported on the package.

Security: the shared SSRF guard runs before every fetch and again on every response.
It resolves the seed's hostname and blocks it when *any* answer is an internal
address (so ``localhost`` no longer slips through), and re-checks the URL the
response landed on so a public seed cannot 30x the scan onto an internal host.
DNS rebinding remains out of scope — see ``utils/_ssrf.py``.
"""

from collections.abc import Iterable
from urllib.parse import urljoin

from polyfetch_scrape.client import fetch
from polyfetch_scrape.contrib.easter_hunt.detectors import DETECTORS, Detector
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import check_redirect, check_ssrf


def _safe_fetch(url: str, *, timeout: float) -> Response | None:
    """Fetch one URL, swallowing FetchError (incl. FingerprintBlock) so a scan continues.

    A redirect onto an internal address raises ValueError through this swallow —
    a blocked target must stop the scan, not be silently skipped.
    """
    try:
        response = fetch(url, timeout=timeout)
    except FetchError:
        return None
    check_redirect(url, response)
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
    seed. A blocked address raises ValueError (not swallowed) — whether the seed is
    a literal internal IP, resolves to one, or redirects to one; a per-URL fetch
    failure is swallowed and the scan moves on.
    """
    path_list = tuple(paths)
    detector_list = tuple(detectors)
    findings: list[Finding] = []
    for seed in seeds:
        for path in path_list:
            url = urljoin(seed, path)
            check_ssrf(url)
            response = _safe_fetch(url, timeout=timeout)
            if response is None:
                continue
            for detector in detector_list:
                findings.extend(detector(response))
    return findings
