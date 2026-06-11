"""End-to-end tests against real network endpoints.

Skipped by default (see `addopts = "-m 'not e2e'"` in pyproject.toml).
Run via `make test_e2e` or `uv run pytest -m e2e`.
"""

import pytest

from polyfetch_scrape import FetchError, RetryPolicy, fetch

pytestmark = pytest.mark.e2e


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


def test_httpbin_404_is_returned_not_retried() -> None:
    # Act
    resp = fetch("https://httpbin.org/status/404")

    # Assert: 404 is terminal, not retried
    assert resp.status == 404


# --- Layer B: real-world targets the roadmap cares about ---


def test_arxiv_abstract_page_succeeds_on_plain_httpx() -> None:
    """arXiv has no anti-bot — confirms stage 0.1.0 covers it."""
    resp = fetch("https://arxiv.org/abs/2301.00001")
    assert resp.status == 200
    assert resp.content_type is not None
    assert "html" in resp.content_type.lower()


def test_arxiv_source_get_real_api() -> None:
    """Stage 0.4.0: source wrapper round-trips against the real arXiv API."""
    from polyfetch_scrape.sources.arxiv import get as arxiv_get

    paper = arxiv_get("2301.00001")
    assert paper.arxiv_id.startswith("2301.00001")
    assert paper.title  # non-empty
    assert len(paper.authors) >= 1
    assert paper.pdf_url.startswith("https://arxiv.org/pdf/")
    assert paper.abs_url.startswith("https://arxiv.org/abs/")


def test_cloudflare_fronted_target_succeeds_via_curl_cffi() -> None:
    """Stage 0.2.0: curl_cffi TLS fallback unblocks Cloudflare-fronted targets.

    nowsecure.nl is the curl_cffi project's canonical anti-bot demo target.
    Plain httpx gets 403; curl_cffi with chrome impersonation gets 200.
    """
    resp = fetch("https://nowsecure.nl/", retry=RetryPolicy(max_attempts=1))
    assert resp.status == 200
    assert resp.backend == "curl_cffi", "expected the fallback to engage"


def test_playwright_backend_executes_against_real_target() -> None:
    """Stage 0.3.0: direct-call proof that the Playwright tier executes correctly.

    No public target cleanly distinguishes 'needs Playwright' from 'curl_cffi
    works' in headless CI (headed Chrome would be needed for hardened
    Cloudflare per Patchright's own README — see docs/scraping-landscape.md).
    So we drive playwright_backend.attempt() directly to verify the tier
    connects, runs JS, and returns a well-formed Response.
    """
    from polyfetch_scrape._backends import playwright_backend

    resp = playwright_backend.attempt(
        method="GET",
        url="https://httpbin.org/html",
        headers=None,
        timeout=30.0,
        policy=RetryPolicy(max_attempts=1),
    )
    assert resp.status == 200
    assert resp.backend == "playwright"
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
