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

- **Fail-open on an unresolvable name — for** :func:`check_ssrf` **and**
  :func:`resolve_pinned` **themselves.** A hostname that does not resolve at all
  (:class:`socket.gaierror`) passes through unchecked — the HTTP client cannot
  connect to an address that doesn't exist either, so refusing it here would
  only turn every offline/DNS-flaky run into a hard error for no security gain.
  :func:`guarded_fetch` is the one exception: it *fails closed* instead, because
  "nothing to pin" there would otherwise mean an unpinned fetch with no guard
  on where a followed redirect lands (see its own docstring).
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
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

from polyfetch_scrape.client import Tier, fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_LITERAL_MSG = "SSRF guard: blocked internal address {addr!r}"
_RESOLVED_MSG = "SSRF guard: blocked host {host!r} resolving to internal address {addr!r}"

# A userinfo ("@"), backslash, percent-encoding, whitespace, or control character in
# the netloc is exactly the kind of form urlsplit and curl could parse differently —
# guarded_fetch refuses any of these outright rather than relying on urlsplit's own
# (possibly curl-incompatible) idea of what the host is (#240 follow-up).
_UNSAFE_NETLOC_RE = re.compile(r"[@\\%\s\x00-\x1f\x7f]")

# RFC-1035-shaped hostname: dot-separated labels, 1-63 chars each, alphanumeric with
# interior hyphens, optional trailing dot. Matches a plain ASCII host AND an
# IDNA/punycode one ("xn--..." labels are alphanumeric-plus-hyphen); never an IP
# literal, which is checked separately via :func:`_parse_ip` first.
_ASCII_HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*\.?$"
)


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

    **Fails closed when nothing can be pinned.** For an external seed, a hop whose
    address :func:`resolve_pinned` cannot verify (a hostless URL, or a hostname that
    does not resolve — both normally fail-open for :func:`check_ssrf`'s own direct
    callers) raises ``FetchError`` here instead of falling through to an unpinned
    fetch: unpinned, curl_cffi's own ``allow_redirects=True`` session default would
    auto-follow a redirect chain with nothing checking where it landed, regressing on
    the pre-#240 check-then-fetch-then-``check_redirect`` behaviour this replaces. An
    internal seed keeps today's unpinned fail-open behaviour unchanged (see the
    module docstring's escalation-only model) — ``check_ssrf``/``resolve_pinned``
    themselves are unaffected either way.

    **Defence in depth, three layers for an external seed.** (1) :func:`_ascii_pin_url`
    rewrites the hop's URL so its host is the exact ASCII/IDNA form that will also be
    resolved and pinned — see its own docstring for why a *single* IDNA conversion,
    shared with resolution, closes a curl-specific gap a naive pin does not. (2) The
    resulting pin is threaded straight into that hop's ``fetch()`` call. (3)
    :func:`check_redirect` is still applied to the landed response on every hop —
    re-checking ``Response.url`` and any unfollowed 301/308 ``Location`` guards
    against a pin bypass (on curl_cffi, there's a fourth and final layer: the
    connected-to address is cross-checked against the pin — see
    ``_backends/curl_backend.py``) actually landing somewhere internal. ``Response.url``
    itself reflects the ASCII-rewritten URL that was actually fetched, not necessarily
    the original (possibly-unicode) one passed in.
    """
    current = url
    for _ in range(max_redirects + 1):
        pin: str | None = None
        pinned_host: str | None = None
        if not seed_is_internal:
            current = _ascii_pin_url(current)
            pin = resolve_pinned(current, seed_is_internal=False)
            if pin is None:
                raise FetchError(
                    f"SSRF guard: no verified address to pin for {current!r} "
                    "(unresolvable host) — refusing to fetch unpinned"
                )
            pinned_host = urlsplit(current).hostname
        resp = fetch(
            current,
            max_tier=max_tier,
            timeout=timeout,
            pinned_ip=pin,
            pinned_host=pinned_host,
        )
        check_redirect(current, resp, seed_is_internal=seed_is_internal)
        target = resp.redirect_to
        if not target:
            return resp
        current = urljoin(current, target)
    raise FetchError(f"too many redirects ({max_redirects} hops): {url}")


def _ascii_pin_url(url: str) -> str:
    """Rewrite ``url``'s netloc to the ASCII/IDNA form that will be both resolved and
    pinned, raising ``FetchError`` before any resolution or fetch if that can't be
    done safely.

    **Why this exists (#240 follow-up).** Pinning a non-ASCII host used to rely on
    two *independent* IDNA conversions landing on the same string: Python's stdlib
    ``str.encode("idna")`` codec (IDNA2003) for the ``CurlOpt.RESOLVE`` key, vs.
    libcurl's own internal conversion (IDNA2008) for the actual DNS lookup it performs
    on the connect URL. When those two disagree, the RESOLVE override silently misses
    and curl falls back to its own (unchecked) DNS — the real request then reaches an
    address nothing here ever verified, before ``curl_backend.py``'s post-request
    ``primary_ip`` check even runs. Converting the host to ASCII exactly ONCE, here,
    with the same codec :func:`socket.getaddrinfo` uses for :func:`_resolve` (so this
    is the identical conversion :func:`resolve_pinned` already resolves against),
    and rewriting the URL itself to that ASCII form before anything downstream sees
    it, means there is only ever one IDNA conversion in the whole pinning path — curl
    receives a pure-ASCII host and does no IDNA conversion of its own, so the RESOLVE
    key matches by construction, not by two codecs agreeing.

    **The strict host gate.** A userinfo (``@``), backslash, percent-encoding,
    whitespace, or control character in the netloc is refused outright — any of these
    is exactly the kind of form ``urlsplit`` (what this guard inspects) and curl's own
    URL/host parser could disagree about. The resulting ASCII host must then be either
    an IP literal or match :data:`_ASCII_HOSTNAME_RE` (RFC-1035-shaped); anything else
    is refused too. This removes the ``urlsplit``-vs-curl parser-differential surface
    at the root, rather than trying to enumerate every way the two could disagree.
    """
    parts = urlsplit(url)
    if _UNSAFE_NETLOC_RE.search(parts.netloc):
        raise FetchError(f"SSRF guard: refusing an unsafe URL form: {url!r}")
    host = parts.hostname
    if host is None:
        raise FetchError(f"SSRF guard: no host to pin: {url!r}")
    literal = _parse_ip(host)
    if literal is not None:
        netloc_host = f"[{host}]" if isinstance(literal, ipaddress.IPv6Address) else host
    else:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise FetchError(f"SSRF guard: could not encode host {host!r}: {url!r}") from exc
        if not _ASCII_HOSTNAME_RE.match(ascii_host):
            raise FetchError(f"SSRF guard: refusing non-hostname host {ascii_host!r}: {url!r}")
        netloc_host = ascii_host
    netloc = netloc_host if parts.port is None else f"{netloc_host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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
