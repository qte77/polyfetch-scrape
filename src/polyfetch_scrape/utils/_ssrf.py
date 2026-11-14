"""SSRF guard shared by the utils that fetch attacker-influenced URLs.

Extracted from ``utils.sitemap`` so ``utils.discovery`` and the ``easter_hunt``
contrib reuse the exact same guard rather than carrying three copies.

**Escalation-only model (#181, relaxed by owner decision).** The *seed* — the URL
or domain a caller explicitly passes in (``discover(url)``'s argument, the
sitemap ``domain``, each ``hunt()`` seed) — is **never blocked**, including a
literal internal IP or a name resolving to one (``localhost``, a LAN alias).
polyfetch is happy to point these utils at a local dev server. The guard only
gates what the tool goes on to fetch **from** that seed — sitemap/sitemap-index
entries, feed/``llms.txt``/JSON-LD links, well-known paths, and redirect
targets — and only when the seed itself is **external**: an internal seed
already means the caller trusts everything reachable from it, so nothing
derived from it is checked either.

:func:`is_seed_internal` computes this seed verdict. Call it **once** per
``discover()``/``fetch_sitemap_urls()``/``hunt()``-per-seed run and thread the
boolean result through :func:`check_ssrf` / :func:`check_redirect` as
``seed_is_internal`` for every derived URL in that run — this avoids
re-resolving the same seed host on every call.

When the seed is external, "internal" is an **allowlist**, not a list of named
ranges: an address is internal unless :attr:`ipaddress.IPv4Address.is_global` /
:attr:`~ipaddress.IPv6Address.is_global` says it is globally routable, or it is
multicast (``is_global`` is ``True`` for some multicast ranges, so that check
stays explicit alongside the allowlist). Checking named flags individually
(``is_private``, ``is_loopback``, ``is_link_local``, ``is_unspecified``,
``is_reserved``) missed **shared/CGNAT address space** (RFC 6598,
``100.64.0.0/10``) — none of those flags cover it, only ``is_global`` does —
and that range hosts real cloud instance-metadata endpoints (e.g. Alibaba
Cloud's ``100.100.100.200``). A literal internal IP — IPv4, IPv6, or an
IPv4-mapped IPv6 literal such as ``::ffff:127.0.0.1`` — is rejected outright; a
*hostname* is resolved and **every** address it maps to (A and AAAA) must be
external.

Redirect targets go through the same check via :func:`check_redirect`: the URL a
response actually landed on, and an unfollowed 301/308 ``Location``, are both
re-checked (when the seed is external) so a public seed cannot bounce a guarded
fetch onto an internal address.

Two limits are deliberate, not oversights:

- **Fail-open on an unresolvable name.** A hostname that does not resolve at all
  (:class:`socket.gaierror`) passes through unchecked — the HTTP client cannot
  connect to an address that doesn't exist either, so refusing it here would
  only turn every offline/DNS-flaky run into a hard error for no security gain.
- **`check_redirect` is preventive on `httpx`, post-hoc on `curl_cffi` and the
  browser tier — unless the caller goes through :func:`guarded_fetch`.**
  `httpx` does not follow redirects itself, so the unfollowed ``Location`` is
  checked *before* any connection is made. `curl_cffi` (``allow_redirects``
  defaults to ``True``) and Patchright (``page.goto`` always follows) have
  already connected to the redirect target by the time this check runs on the
  landed response — it still stops the response body from reaching the
  caller/detectors, but it does not prevent that one request. The three call
  sites capped at ``max_tier="curl_cffi"`` (``utils.sitemap``,
  ``utils.discovery``) now go through :func:`guarded_fetch` instead, which
  re-checks and pins *before every hop*, so the connect itself is prevented on
  both tiers it drives, not just httpx. Patchright has no equivalent per-hop
  pin (closest primitive, ``--host-resolver-rules``, is launch-time-static) so
  it stays post-hoc — see ``contrib/easter_hunt/orchestrator.py``'s docstring.

Out of scope: **DNS rebinding** for any caller still using the bare
`check_ssrf`/`check_redirect` pair (the resolver's answer can change between
that check and the connection) — closing it needs connecting to a pinned IP,
which :func:`guarded_fetch` now does for the httpx/curl_cffi tiers (#240 scope
a; Patchright still lacks a per-hop pin, see above). Obfuscated literal
encodings (decimal/hex/octal) are unchanged: they are not valid hosts for
:func:`ipaddress.ip_address`, so they take the resolver path and are judged on
what they actually resolve to.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

from polyfetch_scrape.client import Tier, fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_LITERAL_MSG = "SSRF guard: blocked internal address {addr!r}"
_RESOLVED_MSG = "SSRF guard: blocked host {host!r} resolving to internal address {addr!r}"


def is_seed_internal(seed: str) -> bool:
    """Whether ``seed``'s host is a literal internal address, or resolves to one.

    Call this **once** per run (per ``discover()``/``fetch_sitemap_urls()`` call,
    or per seed in ``hunt()``) and pass the result to every :func:`check_ssrf` /
    :func:`check_redirect` call for that run as ``seed_is_internal`` — see the
    module docstring's escalation-only model.

    A hostless seed (malformed or relative) reads as **not** internal: there is
    no host to trust, so derived URLs still go through the normal check instead
    of silently inheriting a blanket trust grant.
    """
    host = urlsplit(seed).hostname
    if host is None:
        return False
    literal = _parse_ip(host)
    if literal is not None:
        return _is_internal(literal)
    return any(
        _is_internal(resolved)
        for address in _resolve(host)
        if (resolved := _parse_ip(address)) is not None
    )


def resolve_pinned(url: str, *, seed_is_internal: bool) -> str | None:
    """Like :func:`check_ssrf`, but returns the externally-verified address to
    CONNECT to, instead of only a pass/raise verdict.

    ``None`` means "nothing to pin" — ``seed_is_internal``, a hostless ``url``,
    or an unresolvable hostname (fail-open, same cases as ``check_ssrf``).
    Otherwise the literal IP, or the FIRST resolved address: the exact one just
    verified external, so the caller connects to the address THIS check
    examined and never re-resolves (closes the DNS-rebinding TOCTOU — #240
    gap 1). Still raises ``ValueError`` for an internal literal or an internal
    resolved answer, same as ``check_ssrf``.
    """
    if seed_is_internal:
        return None
    host = urlsplit(url).hostname
    if host is None:
        return None
    literal = _parse_ip(host)
    if literal is not None:
        if _is_internal(literal):
            raise ValueError(_LITERAL_MSG.format(addr=host))
        return host
    verified: list[str] = []
    for address in _resolve(host):
        resolved = _parse_ip(address)
        if resolved is not None:
            if _is_internal(resolved):
                raise ValueError(_RESOLVED_MSG.format(host=host, addr=address))
            verified.append(address)
    return verified[0] if verified else None


def check_ssrf(url: str, *, seed_is_internal: bool) -> None:
    """Block a *derived* ``url`` when the seed is external and ``url`` is internal.

    ``url`` is something the tool is about to fetch **because of** a seed, not
    the seed itself — the seed is never checked (see the module docstring).
    When ``seed_is_internal`` is ``True`` this is a no-op: an internal seed
    means the caller already trusts everything reachable from it. Otherwise
    raises ``ValueError`` before any connection is made for a literal IP, and
    before the caller's own connection for a resolved hostname. A hostless URL
    and a name that does not resolve pass through either way (fail-open, see
    the module docstring). A thin wrapper over :func:`resolve_pinned`, kept so
    existing callers/signature stay unchanged.
    """
    resolve_pinned(url, seed_is_internal=seed_is_internal)


def check_redirect(requested_url: str, response: Response, *, seed_is_internal: bool) -> None:
    """Re-apply :func:`check_ssrf` to where ``response`` landed, or points next.

    No-op when ``seed_is_internal`` (see the module docstring). Otherwise:
    ``response.url`` is the final URL after whatever redirects the serving tier
    followed itself; ``permanent_redirect_to`` is the unfollowed ``Location`` of
    a 301/308. Both are attacker-controlled, so both get the guard; a relative
    target is resolved against ``requested_url`` first. A target identical to
    ``requested_url`` is skipped — it was already checked pre-fetch.

    Raises ``ValueError`` — deliberately not a ``FetchError`` — so a caller that
    swallows fetch failures still surfaces a blocked redirect loudly. See the
    module docstring for which tiers this check is preventive vs. post-hoc on.
    """
    if seed_is_internal:
        return
    for target in (response.url, response.permanent_redirect_to):
        if not target:
            continue
        absolute = urljoin(requested_url, target)
        if absolute != requested_url:
            check_ssrf(absolute, seed_is_internal=False)


def guarded_fetch(
    url: str,
    *,
    seed_is_internal: bool,
    max_tier: Tier = "curl_cffi",
    timeout: float = 30.0,
    max_redirects: int = 10,
) -> Response:
    """``check_ssrf`` + ``fetch`` + ``check_redirect``, replaced by one call that
    pins and re-checks EVERY hop *before* it is fetched.

    Unlike the bare ``check_ssrf``/``fetch``/``check_redirect`` sequence (preventive
    on httpx, post-hoc on curl_cffi — see the module docstring), each hop's address
    is verified via :func:`resolve_pinned` and threaded straight into that hop's
    ``fetch()`` call as ``pinned_ip``/``pinned_host`` — closing both the DNS-rebinding
    TOCTOU (gap 1) and the post-hoc-only redirect check on curl_cffi (gap 2). Follows
    up to ``max_redirects`` hops (``Response.redirect_to`` — any unfollowed 3xx, a
    superset of ``permanent_redirect_to``, #260); raises ``FetchError`` past that — a
    hop-count overrun is a different failure class than a block (the chain never left
    verified-external addresses), so it is swallowable the same way a 404 is by the
    existing ``except FetchError: return None`` call sites, unlike the ``ValueError``
    a block raises.
    """
    current = url
    for _ in range(max_redirects + 1):
        pin = resolve_pinned(current, seed_is_internal=seed_is_internal)
        resp = fetch(
            current,
            max_tier=max_tier,
            timeout=timeout,
            pinned_ip=pin,
            pinned_host=urlsplit(current).hostname if pin else None,
        )
        target = resp.redirect_to
        if not target:
            return resp
        current = urljoin(current, target)
    raise FetchError(f"too many redirects ({max_redirects} hops): {url}")


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
    """Allowlist, not a list of named ranges — see the module docstring."""
    addr = _unmap(addr)
    return not addr.is_global or addr.is_multicast


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
