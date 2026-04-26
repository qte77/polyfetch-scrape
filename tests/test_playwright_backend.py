from typing import Any
from unittest.mock import MagicMock

import pytest
from patchright import sync_api as pw_sync

from polyfetch_scrape._backends import FingerprintBlock, playwright_backend
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polyfetch_scrape._backends.playwright_backend.time.sleep", lambda _s: None
    )


def _make_pw_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    goto_side_effect: Any = None,
    response_status: int = 200,
    response_headers: dict[str, str] | None = None,
    page_content: str = "<html><body>ok</body></html>",
    final_url: str = "https://example.com/",
) -> tuple[MagicMock, MagicMock]:
    """Wire a complete sync_playwright() -> page chain. Returns (page, response_mock)."""
    response = MagicMock(spec=pw_sync.Response)
    response.status = response_status
    response.all_headers.return_value = response_headers or {"content-type": "text/html"}

    page = MagicMock(spec=pw_sync.Page)
    page.url = final_url
    page.content.return_value = page_content
    if goto_side_effect is not None:
        page.goto.side_effect = goto_side_effect
    else:
        page.goto.return_value = response

    context = MagicMock(spec=pw_sync.BrowserContext)
    context.new_page.return_value = page

    browser = MagicMock(spec=pw_sync.Browser)
    browser.new_context.return_value = context

    chromium = MagicMock()
    chromium.launch.return_value = browser

    pw_instance = MagicMock(spec=pw_sync.Playwright)
    pw_instance.chromium = chromium

    pw_cm = MagicMock()
    pw_cm.__enter__ = MagicMock(return_value=pw_instance)
    pw_cm.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        "polyfetch_scrape._backends.playwright_backend.sync_playwright",
        MagicMock(return_value=pw_cm),
    )
    return page, response


def test_playwright_backend_returns_response_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    _make_pw_chain(monkeypatch)

    # Act
    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    # Assert
    assert resp.status == 200
    assert resp.backend == "playwright"
    assert b"ok" in resp.body
    assert resp.content_type == "text/html"


def test_playwright_backend_raises_fingerprintblock_on_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(monkeypatch, response_status=403)

    with pytest.raises(FingerprintBlock):
        playwright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )


def test_playwright_backend_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call raises TimeoutError; second succeeds
    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {}

    page, _ = _make_pw_chain(
        monkeypatch, goto_side_effect=[pw_sync.TimeoutError("nav timeout"), response_ok]
    )

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    assert resp.status == 200
    assert page.goto.call_count == 2


def test_playwright_backend_raises_fetcherror_on_persistent_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(
        monkeypatch, goto_side_effect=pw_sync.TimeoutError("perma timeout")
    )

    with pytest.raises(FetchError):
        playwright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )


def test_playwright_backend_passes_wait_for_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        wait_for_selector="#main",
    )

    page.wait_for_selector.assert_called_once_with("#main", timeout=5000)


def test_playwright_backend_omits_wait_for_selector_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page.wait_for_selector.assert_not_called()
