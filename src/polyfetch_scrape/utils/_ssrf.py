"""SSRF guard shared by the utils that fetch attacker-influenced URLs.

Extracted from ``utils.sitemap`` so ``utils.discovery`` and the ``easter_hunt``
contrib reuse the exact same guard rather than carrying three copies.

The guard is **DNS-aware** (#181). A literal internal IP — IPv4, IPv6, or an
IPv4-mapped IPv6 literal such as ``::ffff:127.0.0.1`` — is rejected outright, as
before; a *hostname* is resolved first and **every** address it maps to (A and
AAAA) must be external before the caller connects. That closes the hole where
``localhost``, a name pinned to ``169.254.169.254``, or a name answering with one
public and one RFC1918 address sailed through the old literal-IP-only check.

Redirect targets go through the same check via :func:`check_redirect`: the URL a
response actually landed on, and an unfollowed 301/308 ``Location``, are both
re-checked so a public host cannot bounce a guarded fetch onto an internal one.

Two limits are deliberate, not oversights:

- **Fail-open on an unresolvable name.** A hostname that does not resolve at all
  (:class:`socket.gaierror`) passes through unchecked — the HTTP client cannot
  connect to an address that doesn't exist either, so refusing it here would
  only turn every offline/DNS-flaky run into a hard error for no security gain.
- **`check_redirect` is preventive on `httpx`, post-hoc on `curl_cffi` and the
  browser tier.** `httpx` does not follow redirects itself, so the unfollowed
  ``Location`` is checked *before* any connection is made. `curl_cffi`
  (``allow_redirects`` defaults to ``True``) and Patchright (``page.goto``
  always follows) have already connected to the redirect target by the time
  this check runs on the landed response — it still stops the response body
  from reaching the caller/detectors, but it does not prevent that one request.

Out of scope: **DNS rebinding** — the resolver's answer can change between this
check and the connection. Closing that needs connecting to a pinned IP, which
none of ``httpx``, ``curl_cffi``, nor Patchright expose (tracked as a follow-up
issue). Obfuscated literal encodings (decimal/hex/octal) are unchanged: they are
not valid hosts for :func:`ipaddress.ip_address`, so they take the resolver path
and are judged on what they actually resolve to.
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

    Raises ``ValueError`` before any connection is made for a literal IP, and
    before the caller's own connection for a resolved hostname. A hostless URL
    (a malformed or relative seed) and a name that does not resolve pass
    through (see the module docstring's "fail-open" note).
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
    """Re-apply :func:`check_ssrf` to where ``response`` landed, or points next.

    ``response.url`` is the final URL after whatever redirects the serving tier
    followed itself; ``permanent_redirect_to`` is the unfollowed ``Location`` of
    a 301/308. Both are attacker-controlled, so both get the guard; a relative
    target is resolved against ``requested_url`` first. A target identical to
    ``requested_url`` is skipped — it was already checked pre-fetch.

    Raises ``ValueError`` — deliberately not a ``FetchError`` — so a caller that
    swallows fetch failures still surfaces a blocked redirect loudly. See the
    module docstring for which tiers this check is preventive vs. post-hoc on.
    """
    for target in (response.url, response.permanent_redirect_to):
        if not target:
            continue
        absolute = urljoin(requested_url, target)
        if absolute != requested_url:
            check_ssrf(absolute)


def _parse_ip(value: str) -> _IPAddress | None:
    """``value`` as an IP address, or ``None`` when it is not a literal IP (a DNS name)."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _unmap(addr: _IPAddress) -> _IPAddress:
    """The embedded IPv4 address of an IPv4-mapped IPv6 literal, else ``addr`` unchanged.

    Checked explicitly, independent of any given Python version's own
    classification of the ``::ffff:a.b.c.d`` form, so the internal/external
    verdict for an IPv4-mapped address never depends on interpreter version.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_internal(addr: _IPAddress) -> bool:
    addr = _unmap(addr)
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

    Fails open on ``socket.gaierror`` — see the module docstring.
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    # sockaddr is (host, port) for IPv4 and (host, port, flowinfo, scope_id) for IPv6,
    # so element 0 is typed str | int. Keep only the str form — an int there would not
    # be an address we could check anyway.
    return [addr for info in infos if isinstance(addr := info[4][0], str)]
