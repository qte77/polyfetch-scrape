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


@pytest.mark.xfail(
    reason="Cloudflare-fronted; expected to fail until stage 0.2.0 (curl_cffi).",
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_cloudflare_fronted_target_demonstrates_0_2_0_gap() -> None:
    """Documents the gap that stage 0.2.0 (curl_cffi TLS fallback) will fill.

    Either: plain httpx is blocked (FetchError or 403) — xfail passes.
    Or:     site happens to allow us through — xfail flips to xpassed.
    """
    resp = fetch("https://www.g2.com/", retry=RetryPolicy(max_attempts=1))
    assert resp.status == 200
