"""SSRF guard shared by the utils that fetch attacker-influenced URLs.

Extracted from ``utils.sitemap`` so ``utils.discovery`` and the ``easter_hunt``
contrib reuse the exact same guard rather than carrying three copies.

The guard is **DNS-aware** (#181). A literal internal IP is rejected outright, as
before; a *hostname* is resolved first and **every** address it maps to (A and
AAAA) must be external before the caller connects. That closes the hole where
``localhost``, a name pinned to ``169.254.169.254``, or a name answering with one
public and one RFC1918 address sailed through the old literal-IP-only check.

Redirect targets go through the same check via :func:`check_redirect`: a public
host that 30x-es to an internal address must not hand its body back to the caller.

Out of scope: **DNS rebinding** — the resolver's answer can change between this
check and the connection. Closing that needs connecting to a pinned IP, which
neither ``httpx``, ``curl_cffi`` nor the browser tier expose. Obfuscated literal
encodings (decimal/hex/octal) are likewise unchanged: they are not valid hosts
for :func:`ipaddress.ip_address`, so they take the resolver path and are judged
on what they actually resolve to.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from polyfetch_scrape.response import Response

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_LITERAL_MSG = "SSRF guard: blocked internal address {addr!r}"
_RESOLVED_MSG = "SSRF guard: blocked host {host!r} resolving to internal address {addr!r}"


def check_ssrf(url: str) -> None:
    """Block ``url`` when its host is — or resolves to — an internal address.

    Raises ``ValueError`` before any connection is made. A hostless URL (a
    malformed or relative seed) and a name that does not resolve pass through.
    """
    host = urlsplit(url).hostname
    if host is None:
        return
    literal = _parse_ip(host)
    if literal is not None:
        if _is_internal(literal):
            raise ValueError(_LITERAL_MSG.format(addr=host))
        return
    for address in _resolve(host):
        resolved = _parse_ip(address)
        if resolved is not None and _is_internal(resolved):
            raise ValueError(_RESOLVED_MSG.format(host=host, addr=address))


def check_redirect(requested_url: str, response: Response) -> None:
    """Apply :func:`check_ssrf` to where ``response`` landed, or points next.

    ``response.url`` is the final URL after whatever redirects the serving tier
    followed itself (``curl_cffi`` and the browser tier do; ``httpx`` does not),
    and ``permanent_redirect_to`` is the unfollowed ``Location`` of a 301/308.
    Both are attacker-controlled, so both get the pre-fetch guard's treatment;
    relative targets are resolved against ``requested_url`` first.

    Raises ``ValueError`` — deliberately not a ``FetchError``, so a caller that
    swallows fetch failures still surfaces a blocked redirect loudly.
    """
    for target in (response.url, response.permanent_redirect_to):
        if not target:
            continue
        absolute = urljoin(requested_url, target)
        if absolute != requested_url:  # same URL back → already checked pre-fetch
            check_ssrf(absolute)


def _parse_ip(value: str) -> _IPAddress | None:
    """``value`` as an IP address, or None when it is not a literal IP (a DNS name)."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_internal(addr: _IPAddress) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_reserved
        or addr.is_multicast
    )


def _resolve(host: str) -> list[str]:
    """Every address ``host`` resolves to (A + AAAA); ``[]`` when resolution fails.

    Fail-open on ``gaierror``: a name this process cannot resolve is a name the
    HTTP client cannot connect to either, so there is nothing left to guard —
    and failing closed would turn every DNS-less/offline run into a hard error.
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]
