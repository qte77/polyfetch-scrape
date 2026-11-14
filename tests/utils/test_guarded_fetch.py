"""``guarded_fetch`` — check + fetch + check_redirect done once per hop, with the
address PINNED: :func:`polyfetch_scrape.utils._ssrf.resolve_pinned`'s verified
address is threaded straight into that same hop's ``fetch()`` call, never
re-resolved for the connect (closes the DNS-rebinding TOCTOU — #240 gap 1). An
internal middle hop is blocked BEFORE it is ever fetched, not detected post-hoc
from a landed response (#240 gap 2).

Both the fetch seam (``..._ssrf.fetch``) and the resolver seam
(``..._ssrf._resolve``) are monkeypatched here, never the real network — same
convention as ``tests/utils/test_ssrf.py``.
"""

import contextlib

import pytest

from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.utils._ssrf import guarded_fetch

_FETCH = "polyfetch_scrape.utils._ssrf.fetch"
_RESOLVER = "polyfetch_scrape.utils._ssrf._resolve"


def _resp(url: str, *, redirect_to: str | None = None) -> Response:
    return Response(
        url=url,
        status=302 if redirect_to else 200,
        headers={},
        body=b"",
        content_type=None,
        backend="httpx",
        redirect_to=redirect_to,
    )


def test_guarded_fetch_pins_the_address_the_check_just_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A rebinding resolver: public on the first call, internal on every call
    # after. The fetch stub must receive the FIRST (public) answer as
    # pinned_ip, and the resolver must be asked only ONCE for this hop — the
    # address resolve_pinned just verified is threaded straight into fetch(),
    # never re-resolved for the connect.
    calls = {"n": 0}

    def _rebinding_resolver(_host: str) -> list[str]:
        calls["n"] += 1
        return ["93.184.216.34"] if calls["n"] == 1 else ["127.0.0.1"]

    monkeypatch.setattr(_RESOLVER, _rebinding_resolver)

    captured: dict[str, object] = {}

    def _fetch_stub(url: str, **kwargs: object) -> Response:
        captured["pinned_ip"] = kwargs.get("pinned_ip")
        captured["pinned_host"] = kwargs.get("pinned_host")
        return _resp(url)

    monkeypatch.setattr(_FETCH, _fetch_stub)

    guarded_fetch("https://public.test/", seed_is_internal=False)

    assert captured["pinned_ip"] == "93.184.216.34"
    assert captured["pinned_host"] == "public.test"
    assert calls["n"] == 1  # resolver queried once for this hop, never re-resolved


def test_guarded_fetch_blocks_before_fetching_a_redirect_into_an_internal_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {"public.test": ["93.184.216.34"], "evil.test": ["127.0.0.1"]}
    monkeypatch.setattr(_RESOLVER, lambda h: list(answers.get(h, ())))

    fetched: list[str] = []

    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        fetched.append(url)
        if url == "https://public.test/a":
            return _resp(url, redirect_to="https://evil.test/b")
        raise AssertionError(f"must not be fetched: {url}")

    monkeypatch.setattr(_FETCH, _fetch_stub)

    with pytest.raises(ValueError, match="SSRF"):
        guarded_fetch("https://public.test/a", seed_is_internal=False)

    assert fetched == ["https://public.test/a"]  # evil.test/b was never fetched


def test_guarded_fetch_follows_a_public_redirect_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_RESOLVER, lambda _h: ["93.184.216.34"])

    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        if url == "https://public.test/a":
            return _resp(url, redirect_to="https://public.test/b")
        return _resp(url)

    monkeypatch.setattr(_FETCH, _fetch_stub)

    resp = guarded_fetch("https://public.test/a", seed_is_internal=False)

    assert resp.url == "https://public.test/b"


def test_guarded_fetch_raises_fetcherror_past_max_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_RESOLVER, lambda _h: ["93.184.216.34"])

    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        # Every hop points at the next one — an 11-hop chain never terminates
        # on its own under max_redirects=10.
        n = int(url.rsplit("/", 1)[-1])
        return _resp(url, redirect_to=f"https://public.test/{n + 1}")

    monkeypatch.setattr(_FETCH, _fetch_stub)

    with pytest.raises(FetchError, match="too many redirects"):
        guarded_fetch("https://public.test/0", seed_is_internal=False, max_redirects=10)


def test_guarded_fetch_internal_seed_skips_the_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def _never(_host: str) -> list[str]:
        raise AssertionError("the resolver must not be reached")

    monkeypatch.setattr(_RESOLVER, _never)

    def _fetch_stub(url: str, **kwargs: object) -> Response:
        assert kwargs.get("pinned_ip") is None
        return _resp(url)

    monkeypatch.setattr(_FETCH, _fetch_stub)

    guarded_fetch("http://169.254.169.254/", seed_is_internal=True)  # must not raise


# --------------------------------------------------------------------------- #
# Fail closed: an external seed with nothing to pin must never fetch unpinned
# --------------------------------------------------------------------------- #


def test_guarded_fetch_fails_closed_when_the_derived_host_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unpinned, curl_cffi's own allow_redirects=True default would auto-follow
    # a redirect chain with nothing checking where it landed — regressing on
    # the pre-#240 check-then-fetch-then-check_redirect behaviour.
    monkeypatch.setattr(_RESOLVER, lambda _h: [])  # unresolvable

    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        raise AssertionError(f"must not fetch unpinned: {url}")

    monkeypatch.setattr(_FETCH, _fetch_stub)

    with pytest.raises(FetchError, match=r"nope\.invalid"):
        guarded_fetch("https://nope.invalid/", seed_is_internal=False)


def test_guarded_fetch_fails_closed_for_a_hostless_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        raise AssertionError(f"must not fetch unpinned: {url}")

    monkeypatch.setattr(_FETCH, _fetch_stub)

    with pytest.raises(FetchError):
        guarded_fetch("/relative/path", seed_is_internal=False)


def test_guarded_fetch_internal_seed_with_unresolvable_host_still_fetches_unpinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail-closed applies only to an external seed — an internal seed keeps
    # today's unpinned behaviour unchanged, even when the host can't resolve.
    def _never(_host: str) -> list[str]:
        raise AssertionError("the resolver must not be reached for an internal seed")

    monkeypatch.setattr(_RESOLVER, _never)

    captured: dict[str, object] = {}

    def _fetch_stub(url: str, **kwargs: object) -> Response:
        captured["pinned_ip"] = kwargs.get("pinned_ip")
        return _resp(url)

    monkeypatch.setattr(_FETCH, _fetch_stub)

    resp = guarded_fetch("http://nope.invalid/", seed_is_internal=True)

    assert captured["pinned_ip"] is None
    assert resp.status == 200


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@public.test/",  # userinfo — urlsplit strips it from .hostname
        "http://public.test\\@evil.test/",  # backslash-before-@ — Python parses host as evil.test
        "http://%70ublic.test/",  # percent-encoded host char — urlsplit does not decode it
    ],
)
def test_guarded_fetch_never_calls_fetch_unpinned_for_tricky_url_forms(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    # Whatever host urlsplit extracts for these parser-edge-case forms, guarded_fetch
    # must either fetch it PINNED or refuse outright — never fall through unpinned.
    answers = {"public.test": ["93.184.216.34"], "evil.test": ["127.0.0.1"]}
    monkeypatch.setattr(_RESOLVER, lambda h: list(answers.get(h, ())))

    def _fetch_stub(fetched_url: str, **kwargs: object) -> Response:
        assert kwargs.get("pinned_ip") is not None, f"fetch called unpinned for {fetched_url!r}"
        return _resp(fetched_url)

    monkeypatch.setattr(_FETCH, _fetch_stub)

    # Either it fetches pinned (asserted inside the stub above), or it refuses
    # outright before ever calling fetch — both are acceptable.
    with contextlib.suppress(ValueError, FetchError):
        guarded_fetch(url, seed_is_internal=False)


# --------------------------------------------------------------------------- #
# Defence in depth: check_redirect still re-checks the landed response
# --------------------------------------------------------------------------- #


def test_guarded_fetch_defense_in_depth_catches_a_landed_url_without_redirect_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A backend quirk: Response.url differs from the requested URL and points
    # internal, but redirect_to is unset, so the hop loop itself would not
    # follow/re-check it — check_redirect (kept as defence in depth) must.
    answers = {"public.test": ["93.184.216.34"], "evil.test": ["127.0.0.1"]}
    monkeypatch.setattr(_RESOLVER, lambda h: list(answers.get(h, ())))

    def _fetch_stub(url: str, **_kwargs: object) -> Response:
        return _resp("http://evil.test/landed")

    monkeypatch.setattr(_FETCH, _fetch_stub)

    with pytest.raises(ValueError, match="SSRF"):
        guarded_fetch("https://public.test/a", seed_is_internal=False)
