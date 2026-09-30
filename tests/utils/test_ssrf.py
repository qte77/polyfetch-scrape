"""Shared SSRF guard — escalation-only model (#181, relaxed by owner decision).

The seed a caller passes in is never checked; only a URL *derived* from an
external seed is checked, via ``check_ssrf(url, seed_is_internal=...)`` /
``check_redirect(requested_url, response, seed_is_internal=...)``.
``is_seed_internal(seed)`` computes the boolean callers thread through.

Two seams are monkeypatched here, never the real network:

* ``..._ssrf._resolve`` — the "what does this name resolve to" seam, used by most
  tests here (the root ``tests/conftest.py`` pins the lower-level
  ``socket.getaddrinfo`` suite-wide; patching ``_resolve`` directly is simpler for
  tests that only care about the guard's own logic).
* ``..._ssrf.socket.getaddrinfo`` — only in the two tests that exercise
  ``_resolve`` itself.
"""

import socket
from collections.abc import Mapping, Sequence

import pytest

from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import _resolve, check_redirect, check_ssrf, is_seed_internal

_RESOLVER = "polyfetch_scrape.utils._ssrf._resolve"
_GETADDRINFO = "polyfetch_scrape.utils._ssrf.socket.getaddrinfo"


def _pin(monkeypatch: pytest.MonkeyPatch, answers: Mapping[str, Sequence[str]]) -> None:
    """Pin DNS to ``answers``; an absent host resolves to nothing (resolution failure)."""
    monkeypatch.setattr(_RESOLVER, lambda host: list(answers.get(host, ())))


def _never_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    def _never(_host: str) -> list[str]:
        raise AssertionError("the resolver must not be reached")

    monkeypatch.setattr(_RESOLVER, _never)


def _resp(url: str, *, permanent_redirect_to: str | None = None) -> Response:
    return Response(
        url=url,
        status=200,
        headers={},
        body=b"",
        content_type=None,
        backend="httpx",
        permanent_redirect_to=permanent_redirect_to,
    )


# --------------------------------------------------------------------------- #
# is_seed_internal — the seed verdict callers compute once per run
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("seed", "answers"),
    [
        ("localhost", ["127.0.0.1"]),
        ("db.internal", ["10.0.0.5"]),
        ("metadata.google.internal", ["169.254.169.254"]),
        ("v6.internal", ["::1"]),
        ("mapped.internal", ["::ffff:127.0.0.1"]),
        ("cgnat.internal", ["100.64.0.1"]),
        # mixed answers: any internal address makes the seed internal too
        ("mixed.internal", ["93.184.216.34", "169.254.169.254"]),
    ],
)
def test_is_seed_internal_true_for_internal_hostname(
    monkeypatch: pytest.MonkeyPatch, seed: str, answers: list[str]
) -> None:
    _pin(monkeypatch, {seed: answers})

    assert is_seed_internal(f"http://{seed}/") is True


def test_is_seed_internal_true_for_literal_internal_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _never_resolve(monkeypatch)

    assert is_seed_internal("http://127.0.0.1/") is True


def test_is_seed_internal_false_for_public_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, {"ok.test": ["93.184.216.34"]})

    assert is_seed_internal("http://ok.test/") is False


def test_is_seed_internal_false_for_literal_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _never_resolve(monkeypatch)

    assert is_seed_internal("http://93.184.216.34/") is False


def test_is_seed_internal_false_for_unresolvable_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, {})

    assert is_seed_internal("http://nope.invalid/") is False


def test_is_seed_internal_false_for_hostless_seed() -> None:
    assert is_seed_internal("/relative/seed") is False


# --------------------------------------------------------------------------- #
# check_ssrf — a no-op when the seed is internal
# --------------------------------------------------------------------------- #


def test_internal_seed_allows_any_derived_url_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_resolve(monkeypatch)

    check_ssrf("http://169.254.169.254/latest/meta-data/", seed_is_internal=True)  # must not raise


def test_internal_seed_allows_a_hostname_that_would_otherwise_be_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_resolve(monkeypatch)

    check_ssrf("http://anything.test/", seed_is_internal=True)  # must not raise


# --------------------------------------------------------------------------- #
# check_ssrf — external seed: derived hostnames are resolved, EVERY answer external
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("host", "answers"),
    [
        ("localhost", ["127.0.0.1"]),  # the alias the literal-IP-only guard let through
        ("db.internal", ["10.0.0.5"]),  # RFC1918
        ("intranet.corp", ["192.168.1.10"]),  # RFC1918 class C
        ("metadata.google.internal", ["169.254.169.254"]),  # cloud IMDS — top SSRF target
        ("v6.internal", ["::1"]),  # IPv6 loopback
        ("linklocal.internal", ["fe80::1"]),  # IPv6 link-local
        ("mapped.internal", ["::ffff:127.0.0.1"]),  # IPv4-mapped IPv6 loopback
        # Shared/CGNAT address space (RFC 6598, 100.64.0.0/10) — not private, not
        # loopback, not link-local, not unspecified, not reserved: none of the old
        # per-flag checks caught it, only the is_global allowlist does.
        ("cgnat.internal", ["100.64.0.1"]),
        # Alibaba Cloud's instance-metadata endpoint lives in that same CGNAT
        # range — the concrete cloud-metadata SSRF target the old check missed.
        ("alibaba-imds.internal", ["100.100.100.200"]),
    ],
)
def test_blocks_derived_hostname_resolving_to_internal_when_seed_external(
    monkeypatch: pytest.MonkeyPatch, host: str, answers: list[str]
) -> None:
    _pin(monkeypatch, {host: answers})

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf(f"http://{host}/latest/meta-data/", seed_is_internal=False)


def test_blocks_when_only_one_of_several_answers_is_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An attacker-controlled name can answer with a public address alongside the
    # real target; a single external answer must not launder the internal one.
    _pin(monkeypatch, {"mixed.test": ["93.184.216.34", "169.254.169.254"]})

    with pytest.raises(ValueError, match="169"):
        check_ssrf("http://mixed.test/", seed_is_internal=False)


def test_error_names_both_the_host_and_the_resolved_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The operator needs to see WHY a public-looking name was blocked.
    _pin(monkeypatch, {"sneaky.test": ["169.254.169.254"]})

    with pytest.raises(ValueError, match=r"sneaky\.test.*169"):
        check_ssrf("http://sneaky.test/", seed_is_internal=False)


def test_allows_hostname_resolving_only_to_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"ok.test": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]})

    check_ssrf("http://ok.test/", seed_is_internal=False)  # must not raise


def test_unresolvable_host_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-open, documented in the module docstring: a name we cannot resolve is
    # a name the HTTP client cannot reach either.
    _pin(monkeypatch, {})

    check_ssrf("http://nope.invalid/", seed_is_internal=False)  # must not raise


def test_hostless_url_passes_through() -> None:
    # A malformed/relative seed has no host to check — must not crash.
    check_ssrf("/relative/path", seed_is_internal=False)


def test_literal_internal_ip_blocked_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The original literal-IP check is preserved and short-circuits the resolver.
    _never_resolve(monkeypatch)

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://169.254.169.254/latest/meta-data/", seed_is_internal=False)


def test_literal_public_ip_allowed_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_resolve(monkeypatch)

    check_ssrf("http://93.184.216.34/", seed_is_internal=False)  # must not raise


def test_literal_ipv4_mapped_internal_blocked_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ::ffff:127.0.0.1 is a literal IPv6 address (ipaddress.ip_address succeeds),
    # so it must be judged as internal without ever reaching the resolver.
    _never_resolve(monkeypatch)

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://[::ffff:127.0.0.1]/", seed_is_internal=False)


def test_literal_ipv4_mapped_public_allowed_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_resolve(monkeypatch)

    check_ssrf("http://[::ffff:93.184.216.34]/", seed_is_internal=False)  # must not raise


@pytest.mark.parametrize(
    "addr",
    [
        "100.64.0.1",  # shared/CGNAT address space (RFC 6598) — not is_global
        "100.100.100.200",  # Alibaba Cloud's instance-metadata endpoint, same range
    ],
)
def test_literal_shared_address_space_blocked_without_any_resolution(
    addr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Not private/loopback/link-local/unspecified/reserved by the old per-flag
    # checks — only the is_global allowlist catches this range.
    _never_resolve(monkeypatch)

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf(f"http://{addr}/", seed_is_internal=False)


def test_literal_multicast_still_blocked_under_the_is_global_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 224.0.0.1 reports is_global == True (multicast is globally scoped in the
    # IANA registry sense), so the allowlist alone would let it through; the
    # guard must keep an explicit multicast check alongside it.
    _never_resolve(monkeypatch)

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://224.0.0.1/", seed_is_internal=False)


def test_credentials_in_url_do_not_hide_an_internal_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # urlsplit strips userinfo, so the hostname still reaches the resolver.
    _pin(monkeypatch, {"db.internal": ["10.0.0.5"]})

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://user:pass@db.internal/", seed_is_internal=False)


# --------------------------------------------------------------------------- #
# _resolve — the resolver seam itself
# --------------------------------------------------------------------------- #


def test_resolve_returns_every_answer_across_families(monkeypatch: pytest.MonkeyPatch) -> None:
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0)),
    ]
    monkeypatch.setattr(_GETADDRINFO, lambda *_a, **_kw: infos)

    assert _resolve("dual.test") == ["93.184.216.34", "::1"]


def test_resolve_fails_open_on_dns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_kw: object) -> object:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(_GETADDRINFO, _boom)

    assert _resolve("nope.invalid") == []


# --------------------------------------------------------------------------- #
# check_redirect — a no-op when the seed is internal
# --------------------------------------------------------------------------- #


def test_internal_seed_allows_any_redirect_target_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_resolve(monkeypatch)
    resp = _resp("http://169.254.169.254/latest/meta-data/")

    check_redirect("http://localhost/", resp, seed_is_internal=True)  # must not raise


# --------------------------------------------------------------------------- #
# check_redirect — external seed: the target a response landed on / points at
# gets the same guard
# --------------------------------------------------------------------------- #


def test_blocks_redirect_that_landed_on_an_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # curl_cffi/browser tiers follow redirects themselves: response.url is where
    # we actually ended up, so it must be re-checked before the body is used.
    _pin(monkeypatch, {"public.test": ["93.184.216.34"], "evil.test": ["127.0.0.1"]})

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect(
            "https://public.test/", _resp("http://evil.test/admin"), seed_is_internal=False
        )


def test_blocks_permanent_redirect_location_to_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # httpx does not follow redirects: the unfollowed 301/308 Location is the target.
    _pin(monkeypatch, {"public.test": ["93.184.216.34"]})
    resp = _resp("https://public.test/", permanent_redirect_to="http://169.254.169.254/latest/")

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect("https://public.test/", resp, seed_is_internal=False)


def test_blocks_redirect_to_a_name_that_resolves_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"public.test": ["93.184.216.34"], "imds.test": ["169.254.169.254"]})
    resp = _resp("https://public.test/", permanent_redirect_to="https://imds.test/")

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect("https://public.test/", resp, seed_is_internal=False)


def test_relative_redirect_target_is_resolved_against_the_request_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"public.test": ["93.184.216.34"]})
    resp = _resp("https://public.test/a", permanent_redirect_to="/b")

    # same public host — must not raise
    check_redirect("https://public.test/a", resp, seed_is_internal=False)


def test_unchanged_url_is_not_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    # No redirect happened; re-resolving would be pure overhead on every fetch.
    _never_resolve(monkeypatch)

    check_redirect("https://public.test/", _resp("https://public.test/"), seed_is_internal=False)
