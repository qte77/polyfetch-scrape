"""End-to-end tests against real network endpoints.

Skipped by default (see `addopts = "-m 'not e2e'"` in pyproject.toml).
Run via `make test_e2e` or `uv run pytest -m e2e`.
"""

import pytest

from polyfetch_scrape import (
    FetchError,
    GoneError,
    RenderOptions,
    RetryPolicy,
    Screenshot,
    fetch,
    render_session,
)
from polyfetch_scrape.utils.sitemap import fetch_sitemap_urls

pytestmark = pytest.mark.e2e

_PNG_MAGIC = b"\x89PNG"


# --- Layer A: httpbin.org (deterministic, behavior-controlled) ---


def test_httpbin_get_returns_200_json() -> None:
    # Act
    resp = fetch("https://httpbin.org/get")

    # Assert
    assert resp.status == 200
    assert resp.content_type is not None
    assert resp.content_type.startswith("application/json")
    assert b'"url"' in resp.body


def test_httpbin_503_retries_then_raises() -> None:
    # Arrange
    policy = RetryPolicy(max_attempts=2, backoff_initial=0.05, backoff_factor=1.0)

    # Act / Assert
    with pytest.raises(FetchError):
        fetch("https://httpbin.org/status/503", retry=policy)


def test_httpbin_404_raises_goneerror() -> None:
    # Act / Assert: 404 is terminal — raises GoneError, not retried
    with pytest.raises(GoneError):
        fetch("https://httpbin.org/status/404")


# --- Layer B: real-world targets the roadmap cares about ---


def test_arxiv_abstract_page_succeeds_on_plain_httpx() -> None:
    """arXiv has no anti-bot — confirms stage 0.1.0 covers it."""
    resp = fetch("https://arxiv.org/abs/2301.00001")
    assert resp.status == 200
    assert resp.content_type is not None
    assert "html" in resp.content_type.lower()


def test_cloudflare_fronted_target_succeeds_via_curl_cffi() -> None:
    """Stage 0.2.0: curl_cffi TLS fallback unblocks Cloudflare-fronted targets.

    nowsecure.nl is the curl_cffi project's canonical anti-bot demo target.
    Plain httpx gets 403; curl_cffi with chrome impersonation gets 200.
    """
    resp = fetch("https://nowsecure.nl/", retry=RetryPolicy(max_attempts=1))
    assert resp.status == 200
    assert resp.backend == "curl_cffi", "expected the fallback to engage"


def test_patchright_backend_executes_against_real_target() -> None:
    """Stage 0.3.0: direct-call proof that the patchright tier executes correctly.

    No public target cleanly distinguishes 'needs the patchright tier' from
    'curl_cffi works' in headless CI (headed Chrome would be needed for hardened
    Cloudflare per Patchright's own README — see docs/scraping-landscape.md).
    So we drive patchright_backend.attempt() directly to verify the tier
    connects, runs JS, and returns a well-formed Response.
    """
    from polyfetch_scrape._backends import patchright_backend

    resp = patchright_backend.attempt(
        method="GET",
        url="https://httpbin.org/html",
        headers=None,
        timeout=30.0,
        policy=RetryPolicy(max_attempts=1),
    )
    assert resp.status == 200
    assert resp.backend == "patchright"
    assert b"<html" in resp.body.lower() or b"<body" in resp.body.lower()


@pytest.mark.xfail(
    reason=(
        "g2.com is Cloudflare Enterprise; passing requires headed real-Chrome "
        "(Patchright README → Best Practice), incompatible with headless CI. "
        "Out of scope for OSS-only toolkit; future fix is commercial bypass or "
        "headed-browser infra."
    ),
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_g2_remains_blocked_in_headless_ci() -> None:
    """Documents the practical ceiling: even Patchright can't beat the hardest
    Cloudflare tier without headed real-Chrome, which CI doesn't provide."""
    resp = fetch("https://www.g2.com/", retry=RetryPolicy(max_attempts=1))
    assert resp.status == 200


# --- Layer C: feature-coverage targets (ToS-safe sandboxes; the weekly probe
# fails loudly if a passing target regresses — e.g. curl_cffi/patchright drift). ---


def test_render_session_drives_js_spa() -> None:
    """render_session (#117) drives an interactive JS SPA and captures a shot."""
    with render_session("https://quotes.toscrape.com/js/", wait_until="networkidle") as s:
        s.wait_for_selector(".quote")
        shot = s.shot("home")
        count = s.page.locator(".quote").count()
    assert count >= 1
    assert shot.startswith(_PNG_MAGIC)
    assert isinstance(s.console_errors, list)


def test_named_screenshots_capture_multiple() -> None:
    """RenderOptions.screenshots (#119) captures named PNGs in one render."""
    resp = fetch(
        "https://quotes.toscrape.com/js/",
        tier="patchright",
        render=RenderOptions(
            wait_until="networkidle",
            screenshots=(Screenshot("viewport", "viewport"), Screenshot("footer", ".footer")),
        ),
    )
    assert set(resp.screenshots) == {"viewport", "footer"}
    assert resp.screenshots["viewport"].startswith(_PNG_MAGIC)
    assert resp.screenshots["footer"].startswith(_PNG_MAGIC)


def test_fetch_sitemap_urls_against_real_sitemap() -> None:
    """fetch_sitemap_urls (#33) resolves a real /sitemap.xml."""
    urls = fetch_sitemap_urls("https://www.sitemaps.org", max_urls=5)
    assert len(urls) >= 1
    assert all(u.startswith("http") for u in urls)


# --- Layer D: harder anti-bot ceilings (ToS-safe challenge sandboxes that 403
# every tier incl. headless Chromium; xfail like g2.com). A weekly xpass here is
# the signal that headless capability improved — see docs/scraping-landscape.md. ---


@pytest.mark.xfail(
    reason="scrapingcourse.com anti-bot challenge 403s all tiers incl. headless (#59 ceiling).",
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_scrapingcourse_antibot_challenge_is_ceiling() -> None:
    resp = fetch(
        "https://www.scrapingcourse.com/antibot-challenge", retry=RetryPolicy(max_attempts=1)
    )
    assert resp.status == 200


@pytest.mark.xfail(
    reason="scrapingcourse.com Cloudflare challenge 403s all tiers incl. headless (#59 ceiling).",
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_scrapingcourse_cloudflare_challenge_is_ceiling() -> None:
    resp = fetch(
        "https://www.scrapingcourse.com/cloudflare-challenge", retry=RetryPolicy(max_attempts=1)
    )
    assert resp.status == 200
