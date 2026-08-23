"""Shared SSRF guard — DNS-aware host validation + redirect targets (#181).

Two seams are monkeypatched here, never the real network:

* ``..._ssrf._resolve`` — the "what does this name resolve to" seam, pinned per
  test to a fixed answer table (tests/conftest.py pins it suite-wide already).
* ``..._ssrf.socket.getaddrinfo`` — only in the two tests that exercise
  ``_resolve`` itself.
"""

import socket
from collections.abc import Mapping, Sequence

import pytest

from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import _resolve, check_redirect, check_ssrf

_RESOLVER = "polyfetch_scrape.utils._ssrf._resolve"
_GETADDRINFO = "polyfetch_scrape.utils._ssrf.socket.getaddrinfo"


def _pin(monkeypatch: pytest.MonkeyPatch, answers: Mapping[str, Sequence[str]]) -> None:
    """Pin DNS to ``answers``; an absent host resolves to nothing (resolution failure)."""
    monkeypatch.setattr(_RESOLVER, lambda host: list(answers.get(host, ())))


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
# check_ssrf — hostnames are resolved, and EVERY answer must be external
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
    ],
)
def test_blocks_hostname_resolving_to_internal(
    monkeypatch: pytest.MonkeyPatch, host: str, answers: list[str]
) -> None:
    _pin(monkeypatch, {host: answers})

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf(f"http://{host}/latest/meta-data/")


def test_blocks_when_only_one_of_several_answers_is_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An attacker-controlled name can answer with a public address alongside the
    # real target; a single external answer must not launder the internal one.
    _pin(monkeypatch, {"mixed.test": ["93.184.216.34", "169.254.169.254"]})

    with pytest.raises(ValueError, match="169"):
        check_ssrf("http://mixed.test/")


def test_error_names_both_the_host_and_the_resolved_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The operator needs to see WHY a public-looking name was blocked.
    _pin(monkeypatch, {"sneaky.test": ["169.254.169.254"]})

    with pytest.raises(ValueError, match=r"sneaky\.test.*169"):
        check_ssrf("http://sneaky.test/")


def test_allows_hostname_resolving_only_to_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"ok.test": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]})

    check_ssrf("http://ok.test/")  # must not raise


def test_unresolvable_host_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-open: a name we cannot resolve is a name the HTTP client cannot reach.
    _pin(monkeypatch, {})

    check_ssrf("http://nope.invalid/")  # must not raise


def test_hostless_url_passes_through() -> None:
    # A malformed/relative seed has no host to check — must not crash.
    check_ssrf("/relative/path")


def test_literal_internal_ip_blocked_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The original literal-IP check is preserved and short-circuits the resolver.
    def _never(_host: str) -> list[str]:
        raise AssertionError("a literal IP must not be sent to the resolver")

    monkeypatch.setattr(_RESOLVER, _never)

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://169.254.169.254/latest/meta-data/")


def test_literal_public_ip_allowed_without_any_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _never(_host: str) -> list[str]:
        raise AssertionError("a literal IP must not be sent to the resolver")

    monkeypatch.setattr(_RESOLVER, _never)

    check_ssrf("http://93.184.216.34/")  # must not raise


def test_credentials_in_url_do_not_hide_an_internal_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # urlsplit strips userinfo, so the hostname still reaches the resolver.
    _pin(monkeypatch, {"db.internal": ["10.0.0.5"]})

    with pytest.raises(ValueError, match="SSRF"):
        check_ssrf("http://user:pass@db.internal/")


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
# check_redirect — the target a response landed on / points at gets the same guard
# --------------------------------------------------------------------------- #


def test_blocks_redirect_that_landed_on_an_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # curl_cffi/browser tiers follow redirects themselves: response.url is where
    # we actually ended up, so it must be re-checked before the body is used.
    _pin(monkeypatch, {"public.test": ["93.184.216.34"], "evil.test": ["127.0.0.1"]})

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect("https://public.test/", _resp("http://evil.test/admin"))


def test_blocks_permanent_redirect_location_to_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # httpx does not follow redirects: the unfollowed 301/308 Location is the target.
    _pin(monkeypatch, {"public.test": ["93.184.216.34"]})
    resp = _resp("https://public.test/", permanent_redirect_to="http://169.254.169.254/latest/")

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect("https://public.test/", resp)


def test_blocks_redirect_to_a_name_that_resolves_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"public.test": ["93.184.216.34"], "imds.test": ["169.254.169.254"]})
    resp = _resp("https://public.test/", permanent_redirect_to="https://imds.test/")

    with pytest.raises(ValueError, match="SSRF"):
        check_redirect("https://public.test/", resp)


def test_relative_redirect_target_is_resolved_against_the_request_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin(monkeypatch, {"public.test": ["93.184.216.34"]})
    resp = _resp("https://public.test/a", permanent_redirect_to="/b")

    check_redirect("https://public.test/a", resp)  # same public host — must not raise


def test_unchanged_url_is_not_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    # No redirect happened; re-resolving would be pure overhead on every fetch.
    def _never(_host: str) -> list[str]:
        raise AssertionError("nothing redirected — the guard must short-circuit")

    monkeypatch.setattr(_RESOLVER, _never)

    check_redirect("https://public.test/", _resp("https://public.test/"))
