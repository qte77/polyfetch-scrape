"""Orchestrator: fetch each seed×path through the public fetch() and run detectors.

Named ``orchestrator`` (not ``hunt``) so the module name never collides with the
public ``hunt`` function re-exported on the package.

Security: a literal-IP SSRF guard runs before every fetch. It is literal-IP only
— DNS names (including ``localhost``) and obfuscated encodings (decimal/hex/octal)
are out of scope for v0.1 and pass through. DNS-based SSRF mitigation is deferred.
"""

import ipaddress
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from polyfetch_scrape.client import fetch
from polyfetch_scrape.contrib.easter_hunt.detectors import DETECTORS, Detector
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response


def _check_ssrf(url: str) -> None:
    """Raise ValueError for a literal private/internal IP host, before any fetch."""
    host = urlsplit(url).hostname
    if host is None:
        return
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return  # not a literal IP — the literal-IP guard does not apply
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise ValueError(f"SSRF guard: blocked internal address {host!r}")


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
    """Scan every seed×path with each detector, returning aggregated Findings.

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
            _check_ssrf(url)
            response = _safe_fetch(url, timeout=timeout)
            if response is None:
                continue
            for detector in detector_list:
                findings.extend(detector(response))
    return findings
