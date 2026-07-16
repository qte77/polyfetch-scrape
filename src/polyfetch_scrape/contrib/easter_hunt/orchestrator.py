"""Orchestrator: fetch each seed x path through the public fetch() and run detectors.

Named ``orchestrator`` (not ``hunt``) so the module name never collides with the
public ``hunt`` function re-exported on the package.

Security: a literal-IP SSRF guard runs before every fetch. It is literal-IP only
— DNS names (including ``localhost``) and obfuscated encodings (decimal/hex/octal)
are out of scope for v0.1 and pass through. DNS-based SSRF mitigation is deferred.
"""

from collections.abc import Iterable
from urllib.parse import urljoin

from polyfetch_scrape.client import fetch
from polyfetch_scrape.contrib.easter_hunt.detectors import DETECTORS, Detector
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import check_ssrf


def _safe_fetch(url: str, *, timeout: float) -> Response | None:
    """Fetch one URL, swallowing FetchError (incl. FingerprintBlock) so a scan continues."""
    try:
        return fetch(url, timeout=timeout)
    except FetchError:
        return None


def hunt(
    seeds: Iterable[str],
    *,
    paths: Iterable[str] = ("/",),
    detectors: Iterable[Detector] = DETECTORS,
    timeout: float = 10.0,
) -> list[Finding]:
    """Scan every seed x path with each detector, returning aggregated Findings.

    Materialise ``paths``/``detectors`` once so single-use iterables survive every
    seed. A blocked literal IP raises ValueError (not swallowed); a per-URL fetch
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
