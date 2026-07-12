"""Literal-IP SSRF guard shared by utils that fetch attacker-influenced URLs.

Extracted from ``utils.sitemap`` so ``utils.discovery`` reuses the exact same
guard rather than carrying a third copy. Literal-IP only: DNS names (incl.
``localhost``) pass through, matching the documented scope shared with the
``easter_hunt`` contrib.
"""

import ipaddress
from urllib.parse import urlsplit


def check_ssrf(url: str) -> None:
    """Block a URL whose host is a literal internal IP (SSRF guard, pre-fetch)."""
    host = urlsplit(url).hostname
    if host is None:
        return
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return  # not a literal IP — DNS name, allowed (literal-IP-only scope)
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise ValueError(f"SSRF guard: blocked internal address {host!r}")
