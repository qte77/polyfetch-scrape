from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from patchright import sync_api as pw_sync

from polyfetch_scrape._backends import FingerprintBlock, patchright_backend
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.render_options import RenderAction, RenderOptions, Screenshot
from polyfetch_scrape.retry import RetryPolicy

_IPHONE_13_DEVICE: dict[str, Any] = {
    "user_agent": "UA-iphone",
    "viewport": {"width": 390, "height": 844},
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 3,
    "default_browser_type": "chromium",
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape._backends.patchright_backend.time.sleep", lambda _s: None)


def _make_pw_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    goto_side_effect: Any = None,
    response_status: int = 200,
    response_headers: dict[str, str] | None = None,
    page_content: str = "<html><body>ok</body></html>",
    final_url: str = "https://example.com/",
    video_path: str = "captured-videos/abc123.webm",
) -> tuple[MagicMock, MagicMock]:
    """Wire a complete sync_playwright() -> page chain. Returns (page, response_mock).

    ``page._test_browser`` exposes the ``browser`` mock so tests can assert on the
    kwargs passed to ``browser.new_context(...)`` without widening the return tuple.
    """
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
    page.video = MagicMock()
    page.video.path.return_value = video_path

    context = MagicMock(spec=pw_sync.BrowserContext)
    context.new_page.return_value = page

    browser = MagicMock(spec=pw_sync.Browser)
    browser.new_context.return_value = context
    page._test_browser = browser

    chromium = MagicMock()
    chromium.launch.return_value = browser

    pw_instance = MagicMock(spec=pw_sync.Playwright)
    pw_instance.chromium = chromium
    pw_instance.devices = {"iPhone 13": dict(_IPHONE_13_DEVICE)}

    pw_cm = MagicMock()
    pw_cm.__enter__ = MagicMock(return_value=pw_instance)
    pw_cm.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr(
        "polyfetch_scrape._backends.patchright_backend.sync_playwright",
        MagicMock(return_value=pw_cm),
    )
    return page, response


def test_patchright_backend_returns_response_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    _make_pw_chain(monkeypatch)

    # Act
    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    # Assert
    assert resp.status == 200
    assert resp.backend == "patchright"
    assert b"ok" in resp.body
    assert resp.content_type == "text/html"


def test_patchright_backend_raises_fingerprintblock_on_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(monkeypatch, response_status=403)

    with pytest.raises(FingerprintBlock):
        patchright_backend.attempt(
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
def test_patchright_backend_raises_terminal_status(
    monkeypatch: pytest.MonkeyPatch, status: int, exc_type: type[Exception]
) -> None:
    _make_pw_chain(monkeypatch, response_status=status)

    with pytest.raises(exc_type):
        patchright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
        )


def test_patchright_backend_deletes_video_on_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A terminal status (404) raised out of _run_page must still delete a recorded video —
    # the context closed and finalized the .webm, but no success Response will reference it.
    page, _ = _make_pw_chain(monkeypatch, response_status=404)

    with pytest.raises(GoneError):
        patchright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
            render=RenderOptions(record_video_dir="vids"),
        )

    page.video.delete.assert_called_once_with()


def test_patchright_backend_surfaces_permanent_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_pw_chain(
        monkeypatch,
        response_status=301,
        response_headers={"location": "https://example.com/new", "content-type": "text/html"},
    )

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com/old",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.status == 301
    assert resp.permanent_redirect_to == "https://example.com/new"


def test_patchright_backend_captures_viewport_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.screenshot.return_value = b"\x89PNG-viewport"

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(screenshot="viewport"),
    )

    page.screenshot.assert_called_once_with()
    assert resp.screenshot == b"\x89PNG-viewport"


def test_patchright_backend_captures_full_page_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.screenshot.return_value = b"\x89PNG-full"

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(screenshot="full_page"),
    )

    page.screenshot.assert_called_once_with(full_page=True)
    assert resp.screenshot == b"\x89PNG-full"


def test_patchright_backend_captures_element_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.locator.return_value.screenshot.return_value = b"\x89PNG-el"

    resp = patchright_backend.attempt(
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


def test_patchright_backend_no_screenshot_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page.screenshot.assert_not_called()
    page.locator.assert_not_called()
    assert resp.screenshot is None


def test_patchright_backend_captures_named_screenshots(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)
    page.screenshot.return_value = b"VP"
    page.locator.return_value.screenshot.return_value = b"EL"

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(
            screenshots=(Screenshot("full", "viewport"), Screenshot("chart", "#chart"))
        ),
    )

    assert resp.screenshots == {"full": b"VP", "chart": b"EL"}
    page.locator.assert_called_once_with("#chart")


def test_patchright_backend_no_screenshots_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.screenshots == {}


def test_patchright_backend_uses_wait_until_from_render(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_until="networkidle"),
    )

    page.goto.assert_called_once_with("https://example.com", wait_until="networkidle", timeout=5000)


def test_patchright_backend_waits_for_function(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_for_function="() => window.ready"),
    )

    page.wait_for_function.assert_called_once_with("() => window.ready", timeout=5000)


def test_patchright_backend_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call raises TimeoutError; second succeeds
    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {}

    page, _ = _make_pw_chain(
        monkeypatch, goto_side_effect=[pw_sync.TimeoutError("nav timeout"), response_ok]
    )

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    assert resp.status == 200
    assert page.goto.call_count == 2


def test_patchright_backend_raises_fetcherror_on_persistent_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(monkeypatch, goto_side_effect=pw_sync.TimeoutError("perma timeout"))

    with pytest.raises(FetchError):
        patchright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )


def test_patchright_backend_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # First response is a retryable 503; second is a 200 — should retry, not return the 503.
    response_503 = MagicMock(spec=pw_sync.Response)
    response_503.status = 503
    response_503.all_headers.return_value = {}

    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {"content-type": "text/html"}

    page, _ = _make_pw_chain(monkeypatch, goto_side_effect=[response_503, response_ok])

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    assert resp.status == 200
    assert page.goto.call_count == 2


def test_patchright_backend_raises_fetcherror_on_persistent_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_pw_chain(monkeypatch, response_status=503)

    with pytest.raises(FetchError) as excinfo:
        patchright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=2),
        )

    # A 5xx is a plain retry-exhaustion FetchError, never the fingerprint (403) path.
    assert not isinstance(excinfo.value, FingerprintBlock)
    assert "status=503" in str(excinfo.value)


def test_patchright_backend_honors_retry_after_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        "polyfetch_scrape._backends.patchright_backend.time.sleep",
        lambda s: delays.append(s),
    )

    response_503 = MagicMock(spec=pw_sync.Response)
    response_503.status = 503
    response_503.all_headers.return_value = {"retry-after": "7"}

    response_ok = MagicMock(spec=pw_sync.Response)
    response_ok.status = 200
    response_ok.all_headers.return_value = {"content-type": "text/html"}

    _make_pw_chain(monkeypatch, goto_side_effect=[response_503, response_ok])

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=2),
    )

    # Server Retry-After wins over exponential backoff.
    assert delays == [7.0]


def test_patchright_backend_passes_wait_for_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(wait_for_selector="#main"),
    )

    page.wait_for_selector.assert_called_once_with("#main", timeout=5000)


def test_patchright_backend_omits_wait_for_selector_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page.wait_for_selector.assert_not_called()


def test_patchright_backend_maps_each_action_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    actions = (
        RenderAction("click", selector="#a"),
        RenderAction("click_text", text="Go"),
        RenderAction("fill", selector="#b", value="hi"),
        RenderAction("wait_for_selector", selector="#c"),
        RenderAction("wait_ms", ms=250),
    )
    patchright_backend.attempt(
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


def test_patchright_backend_runs_actions_before_waits_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
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


def test_patchright_backend_no_actions_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
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


def _fake_console(msg_type: str, text: str) -> MagicMock:
    msg = MagicMock()
    msg.type = msg_type
    msg.text = text
    return msg


def _fake_request(url: str, failure: str) -> MagicMock:
    req = MagicMock()
    req.url = url
    req.failure = failure
    return req


def _fake_response(status: int, url: str) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.url = url
    return resp


def _page_handlers(page: MagicMock) -> dict[str, Any]:
    """Map each registered page.on(event) to its handler from call_args_list."""
    return {c.args[0]: c.args[1] for c in page.on.call_args_list}


def test_patchright_backend_captures_console_and_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(capture_console=True, capture_network_failures=True),
    )

    # resp.console_errors / .network_failures are the SAME list objects the handlers
    # append to, so firing synthetic events after the return is visible on resp.
    handlers = _page_handlers(page)
    handlers["console"](_fake_console("error", "boom"))
    handlers["pageerror"]("Uncaught X")
    handlers["requestfailed"](_fake_request("https://x/api", "net::ERR"))
    handlers["response"](_fake_response(500, "https://x/500"))
    handlers["response"](_fake_response(200, "https://x/ok"))  # sub-400 is not a failure

    assert "boom" in resp.console_errors
    assert "Uncaught X" in resp.console_errors
    assert {"url": "https://x/api", "error": "net::ERR"} in resp.network_failures
    assert {"url": "https://x/500", "status": 500} in resp.network_failures
    assert not any(f.get("url") == "https://x/ok" for f in resp.network_failures)


def test_patchright_backend_console_filter_ignores_non_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(capture_console=True),
    )

    _page_handlers(page)["console"](_fake_console("log", "just a log"))

    assert resp.console_errors == []


def test_patchright_backend_no_capture_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    # Opt-in gating → zero listeners registered, zero overhead.
    registered = {c.args[0] for c in page.on.call_args_list}
    assert registered & {"console", "pageerror", "requestfailed", "response"} == set()
    assert resp.console_errors == []
    assert resp.network_failures == []


# --------------------------------------------------------------------------- #
# context_kwargs: emulation + video option mapping (unit-level, no pw chain)
# --------------------------------------------------------------------------- #


def test_context_kwargs_device_preset_spreads_full_dict() -> None:
    pw = MagicMock()
    pw.devices = {"iPhone 13": dict(_IPHONE_13_DEVICE)}

    kwargs = patchright_backend.context_kwargs(pw, RenderOptions(device="iPhone 13"))

    assert kwargs == _IPHONE_13_DEVICE
    assert kwargs["default_browser_type"] == "chromium"  # NOT stripped


def test_context_kwargs_explicit_viewport_overrides_device_viewport() -> None:
    pw = MagicMock()
    pw.devices = {"iPhone 13": dict(_IPHONE_13_DEVICE)}

    kwargs = patchright_backend.context_kwargs(
        pw, RenderOptions(device="iPhone 13", viewport=(800, 600))
    )

    assert kwargs["viewport"] == {"width": 800, "height": 600}
    assert kwargs["user_agent"] == "UA-iphone"  # untouched device field survives


def test_context_kwargs_maps_emulation_fields() -> None:
    pw = MagicMock()
    pw.devices = {}

    kwargs = patchright_backend.context_kwargs(
        pw, RenderOptions(user_agent="UA-x", locale="en-US", color_scheme="dark")
    )

    assert kwargs == {"user_agent": "UA-x", "locale": "en-US", "color_scheme": "dark"}


def test_context_kwargs_video_dir_and_size() -> None:
    pw = MagicMock()
    pw.devices = {}

    kwargs = patchright_backend.context_kwargs(
        pw, RenderOptions(record_video_dir="captured-vids", record_video_size=(640, 480))
    )

    assert kwargs["record_video_dir"] == "captured-vids"
    assert kwargs["record_video_size"] == {"width": 640, "height": 480}


def test_context_kwargs_video_dir_without_size_omits_size_key() -> None:
    pw = MagicMock()
    pw.devices = {}

    kwargs = patchright_backend.context_kwargs(pw, RenderOptions(record_video_dir="captured-vids"))

    assert kwargs == {"record_video_dir": "captured-vids"}


def test_context_kwargs_empty_opts_is_empty_dict() -> None:
    pw = MagicMock()
    pw.devices = {}

    assert patchright_backend.context_kwargs(pw, RenderOptions()) == {}


def test_context_kwargs_storage_state_path_becomes_string() -> None:
    pw = MagicMock()
    pw.devices = {}

    kwargs = patchright_backend.context_kwargs(
        pw, RenderOptions(storage_state=Path("auth/state.json"))
    )

    assert kwargs == {"storage_state": "auth/state.json"}


def test_context_kwargs_storage_state_mapping_passes_through() -> None:
    pw = MagicMock()
    pw.devices = {}
    state = {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}

    kwargs = patchright_backend.context_kwargs(pw, RenderOptions(storage_state=state))

    assert kwargs == {"storage_state": state}


def test_context_kwargs_extra_http_headers_map() -> None:
    pw = MagicMock()
    pw.devices = {}

    kwargs = patchright_backend.context_kwargs(
        pw, RenderOptions(extra_http_headers={"Authorization": "Bearer t"})
    )

    assert kwargs == {"extra_http_headers": {"Authorization": "Bearer t"}}


def test_fetch_headers_merge_over_render_extra_http_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers={"X-Shared": "from-fetch"},
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(extra_http_headers={"X-Shared": "from-render", "X-Ctx": "keep"}),
    )

    context = page._test_browser.new_context.return_value
    context.set_extra_http_headers.assert_called_once_with(
        {"X-Shared": "from-fetch", "X-Ctx": "keep"}
    )


# --------------------------------------------------------------------------- #
# fetch tier: context kwargs reach browser.new_context; video finalize on close
# --------------------------------------------------------------------------- #


def test_patchright_backend_passes_context_kwargs_to_new_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(device="iPhone 13", locale="en-US"),
    )

    kwargs = page._test_browser.new_context.call_args.kwargs
    assert kwargs["locale"] == "en-US"
    assert kwargs["user_agent"] == "UA-iphone"
    assert kwargs["default_browser_type"] == "chromium"


def test_patchright_backend_new_context_no_kwargs_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    page._test_browser.new_context.assert_called_once_with()


def test_patchright_backend_video_success_sets_video_path(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _make_pw_chain(monkeypatch, video_path="captured-videos/ok.webm")

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(record_video_dir="captured-videos"),
    )

    assert resp.video_path == Path("captured-videos/ok.webm")
    page.video.delete.assert_not_called()


def test_patchright_backend_video_deleted_on_persistent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch, goto_side_effect=pw_sync.TimeoutError("nav timeout"))

    with pytest.raises(FetchError):
        patchright_backend.attempt(
            method="GET",
            url="https://example.com",
            headers=None,
            timeout=5.0,
            policy=RetryPolicy(max_attempts=1),
            render=RenderOptions(record_video_dir="captured-videos"),
        )

    page.video.delete.assert_called_once_with()


def test_patchright_backend_no_video_path_when_not_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _ = _make_pw_chain(monkeypatch)

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=5.0,
        policy=RetryPolicy(max_attempts=1),
    )

    assert resp.video_path is None
    page.video.path.assert_not_called()
    page.video.delete.assert_not_called()
