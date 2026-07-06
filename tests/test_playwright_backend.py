from typing import Any
from unittest.mock import MagicMock

import pytest
from patchright import sync_api as pw_sync

from polyfetch_scrape._backends import FingerprintBlock, playwright_backend
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.render_options import RenderAction, RenderOptions
from polyfetch_scrape.retry import RetryPolicy


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape._backends.playwright_backend.time.sleep", lambda _s: None)


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


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [(401, AuthRequired), (404, GoneError), (451, LegalBlock)],
)
def test_playwright_backend_raises_terminal_status(
    monkeypatch: pytest.MonkeyPatch, status: int, exc_type: type[Exception]
) -> None:
    _make_pw_chain(monkeypatch, response_status=status)

    with pytest.raises(exc_type):
        playwright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )


def test_playwright_backend_surfaces_permanent_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_pw_chain(
        monkeypatch,
        response_status=301,
        response_headers={"location": "https://example.com/new", "content-type": "text/html"},
    )

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com/old",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.status == 301
    assert resp.permanent_redirect_to == "https://example.com/new"


def test_playwright_backend_captures_viewport_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.screenshot.return_value = b"\x89PNG-viewport"

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(screenshot="viewport"),
    )

    page.screenshot.assert_called_once_with()
    assert resp.screenshot == b"\x89PNG-viewport"


def test_playwright_backend_captures_element_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.locator.return_value.screenshot.return_value = b"\x89PNG-el"

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(screenshot="#chart"),
    )

    page.locator.assert_called_once_with("#chart")
    page.locator.return_value.screenshot.assert_called_once_with()
    assert resp.screenshot == b"\x89PNG-el"


def test_playwright_backend_no_screenshot_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page.screenshot.assert_not_called()
    page.locator.assert_not_called()
    assert resp.screenshot is None


def test_playwright_backend_uses_wait_until_from_render(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_until="networkidle"),
    )

    page.goto.assert_called_once_with("https://example.com", wait_until="networkidle", timeout=5000)


def test_playwright_backend_waits_for_function(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_for_function="() => window.ready"),
    )

    page.wait_for_function.assert_called_once_with("() => window.ready", timeout=5000)


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
    _make_pw_chain(monkeypatch, goto_side_effect=pw_sync.TimeoutError("perma timeout"))

    with pytest.raises(FetchError):
        playwright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )


def test_playwright_backend_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # First response is a retryable 503; second is a 200 — should retry, not return the 503.
    response_503 = MagicMock(spec=pw_sync.Response)
    response_503.status = 503
    response_503.all_headers.return_value = {}

    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {"content-type": "text/html"}

    page, _ = _make_pw_chain(monkeypatch, goto_side_effect=[response_503, response_ok])

    resp = playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    assert resp.status == 200
    assert page.goto.call_count == 2


def test_playwright_backend_raises_fetcherror_on_persistent_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(monkeypatch, response_status=503)

    with pytest.raises(FetchError) as excinfo:
        playwright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )

    # A 5xx is a plain retry-exhaustion FetchError, never the fingerprint (403) path.
    assert not isinstance(excinfo.value, FingerprintBlock)
    assert "status=503" in str(excinfo.value)


def test_playwright_backend_honors_retry_after_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        "polyfetch_scrape._backends.playwright_backend.time.sleep",
        lambda s: delays.append(s),
    )

    response_503 = MagicMock(spec=pw_sync.Response)
    response_503.status = 503
    response_503.all_headers.return_value = {"retry-after": "7"}

    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {"content-type": "text/html"}

    _make_pw_chain(monkeypatch, goto_side_effect=[response_503, response_ok])

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    # Server Retry-After wins over exponential backoff.
    assert delays == [7.0]


def test_playwright_backend_passes_wait_for_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_for_selector="#main"),
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


def test_playwright_backend_maps_each_action_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    actions = (
        RenderAction("click", selector="#a"),
        RenderAction("click_text", text="Go"),
        RenderAction("fill", selector="#b", value="hi"),
        RenderAction("wait_for_selector", selector="#c"),
        RenderAction("wait_ms", ms=250),
    )
    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(actions=actions),
    )

    page.click.assert_called_once_with("#a", timeout=5000)
    page.get_by_text.assert_called_once_with("Go")
    page.get_by_text.return_value.click.assert_called_once_with(timeout=5000)
    page.fill.assert_called_once_with("#b", "hi", timeout=5000)
    page.wait_for_selector.assert_called_once_with("#c", timeout=5000)
    page.wait_for_timeout.assert_called_once_with(250)


def test_playwright_backend_runs_actions_before_waits_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(
            actions=(
                RenderAction("click", selector="#a"),
                RenderAction("fill", selector="#b", value="x"),
            ),
            wait_for_selector="#done",
        ),
    )

    # Actions fire in declared order, then _apply_waits' selector wait.
    names = [c[0] for c in page.method_calls]
    ordered = [n for n in names if n in {"click", "fill", "wait_for_selector"}]
    assert ordered == ["click", "fill", "wait_for_selector"]
    page.click.assert_called_once_with("#a", timeout=5000)
    page.fill.assert_called_once_with("#b", "x", timeout=5000)
    page.wait_for_selector.assert_called_once_with("#done", timeout=5000)


def test_playwright_backend_no_actions_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    playwright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page.click.assert_not_called()
    page.fill.assert_not_called()
    page.get_by_text.assert_not_called()
    page.wait_for_timeout.assert_not_called()
