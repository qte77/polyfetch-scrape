import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from patchright import sync_api as pw_sync

from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_session import render_session

# The exported render_session function shadows the submodule attribute, so grab the
# real module object from sys.modules to patch its sync_playwright.
_RS_MOD = sys.modules["polyfetch_scrape.render_session"]

_IPHONE_13_DEVICE: dict[str, Any] = {
    "user_agent": "UA-iphone",
    "viewport": {"width": 390, "height": 844},
    "is_mobile": True,
    "has_touch": True,
    "device_scale_factor": 3,
    "default_browser_type": "chromium",
}


def _make_session_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    goto_side_effect: Any = None,
    screenshot: bytes = b"\x89PNG",
    video_path: str = "captured-videos/session.webm",
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Wire a sync_playwright().start() -> page chain. Returns (page, context, browser, pw)."""
    page = MagicMock(spec=pw_sync.Page)
    page.url = "https://example.com/"
    if goto_side_effect is not None:
        page.goto.side_effect = goto_side_effect
    page.screenshot.return_value = screenshot
    page.video = MagicMock()
    page.video.path.return_value = video_path

    context = MagicMock(spec=pw_sync.BrowserContext)
    context.new_page.return_value = page

    browser = MagicMock(spec=pw_sync.Browser)
    browser.new_context.return_value = context

    pw_instance = MagicMock(spec=pw_sync.Playwright)
    pw_instance.chromium.launch.return_value = browser
    pw_instance.devices = {"iPhone 13": dict(_IPHONE_13_DEVICE)}

    sp = MagicMock()
    sp.start.return_value = pw_instance
    monkeypatch.setattr(_RS_MOD, "sync_playwright", MagicMock(return_value=sp))
    return page, context, browser, pw_instance


def _handlers(page: MagicMock) -> dict[str, Any]:
    return {c.args[0]: c.args[1] for c in page.on.call_args_list}


def _fake_console(msg_type: str, text: str) -> MagicMock:
    msg = MagicMock()
    msg.type = msg_type
    msg.text = text
    return msg


def test_enter_navigates_and_exposes_page(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com", wait_until="networkidle") as s:
        assert s.page is page

    page.goto.assert_called_once_with(
        "https://example.com", wait_until="networkidle", timeout=30000
    )


def test_methods_map_to_page_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com", timeout=5.0) as s:
        s.click("#a")
        s.click_text("Go")
        s.fill("#b", "hi")
        s.submit()
        s.wait_for_selector("#c")
        s.wait_for_function("() => true")
        s.wait_ms(250)

    page.click.assert_called_once_with("#a", timeout=5000)
    page.get_by_text.assert_called_once_with("Go")
    page.get_by_text.return_value.click.assert_called_once_with(timeout=5000)
    page.fill.assert_called_once_with("#b", "hi", timeout=5000)
    page.keyboard.press.assert_called_once_with("Enter")
    page.wait_for_selector.assert_called_once_with("#c", timeout=5000)
    page.wait_for_function.assert_called_once_with("() => true", timeout=5000)
    page.wait_for_timeout.assert_called_once_with(250)


def test_page_default_timeouts_set_from_session_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """#216: raw `s.page` calls (e.g. `s.page.locator(...).click()`) fell back to Playwright's
    own 30000ms default regardless of the session's `timeout=`, silently burning multiples of
    the intended budget. Set both page-level defaults from the session timeout so `.page` and
    the RenderSession convenience methods agree."""
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com", timeout=5.0):
        pass

    page.set_default_timeout.assert_called_once_with(5000)
    page.set_default_navigation_timeout.assert_called_once_with(5000)


def test_shot_stores_named_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch, screenshot=b"PNGDATA")

    with render_session("https://example.com") as s:
        out = s.shot("after")

    assert out == b"PNGDATA"
    assert s.screenshots["after"] == b"PNGDATA"
    page.screenshot.assert_called_once_with()


def test_console_capture_populates(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        handlers = _handlers(page)
        handlers["console"](_fake_console("error", "boom"))
        handlers["pageerror"]("Uncaught Z")

    assert "boom" in s.console_errors
    assert "Uncaught Z" in s.console_errors


def test_teardown_on_normal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, browser, pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com"):
        pass

    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()
    pw.stop.assert_called_once_with()


def test_screenshot_on_exception_and_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, browser, pw = _make_session_chain(monkeypatch, screenshot=b"ERRSHOT")

    with pytest.raises(RuntimeError, match="boom"), render_session("https://example.com") as s:
        raise RuntimeError("boom")

    assert s.screenshots["exception"] == b"ERRSHOT"
    context.close.assert_called_once_with()
    browser.close.assert_called_once_with()
    pw.stop.assert_called_once_with()


def test_goto_timeout_raises_fetcherror(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_session_chain(monkeypatch, goto_side_effect=pw_sync.TimeoutError("nav timeout"))

    with pytest.raises(FetchError), render_session("https://example.com"):
        pass


def test_render_session_exported_from_package_root() -> None:
    import polyfetch_scrape

    assert hasattr(polyfetch_scrape, "render_session")
    assert "render_session" in polyfetch_scrape.__all__


def test_context_kwargs_reach_new_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, _context, browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com", device="iPhone 13", color_scheme="dark"):
        pass

    kwargs = browser.new_context.call_args.kwargs
    assert kwargs["color_scheme"] == "dark"
    assert kwargs["user_agent"] == "UA-iphone"
    assert kwargs["default_browser_type"] == "chromium"


def test_new_context_no_kwargs_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, _context, browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com"):
        pass

    browser.new_context.assert_called_once_with()


def test_video_path_set_after_teardown_when_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch, video_path="captured-videos/session.webm")

    with render_session("https://example.com", record_video_dir="captured-videos") as s:
        assert s.video_path is None  # not finalized until the context closes

    assert s.video_path == Path("captured-videos/session.webm")
    page.video.path.assert_called_once_with()


def test_video_path_read_before_browser_close_and_pw_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (#199): video.path() must be read after context.close() but before
    browser.close()/pw.stop() -- Patchright only finalizes the video once its context has
    closed, and video.path() needs a live driver connection to resolve it.
    """
    page, context, browser, pw = _make_session_chain(
        monkeypatch, video_path="captured-videos/session.webm"
    )
    order: list[str] = []
    context.close.side_effect = lambda: order.append("context.close")
    browser.close.side_effect = lambda: order.append("browser.close")
    pw.stop.side_effect = lambda: order.append("pw.stop")
    page.video.path.side_effect = lambda: (
        order.append("video.path") or "captured-videos/session.webm"
    )

    with render_session("https://example.com", record_video_dir="captured-videos") as s:
        pass

    assert order == ["context.close", "video.path", "browser.close", "pw.stop"]
    assert s.video_path == Path("captured-videos/session.webm")


def test_video_path_none_when_not_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        pass

    assert s.video_path is None
    page.video.path.assert_not_called()


def test_har_path_set_after_teardown_when_recording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _make_session_chain(monkeypatch)
    har = tmp_path / "session.har"

    with render_session("https://example.com", record_har_path=str(har)) as s:
        assert s.har_path is None  # not set until the context closes

    assert s.har_path == har


def test_har_path_set_before_browser_close_and_pw_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#229: mirrors the #199 ordering lesson. Patchright writes the HAR on context.close(),
    so har_path must be set right after that -- not deferred until browser.close()/pw.stop()."""
    _page, context, browser, pw = _make_session_chain(monkeypatch)
    har = tmp_path / "session.har"
    order: list[str] = []
    holder: dict[str, Any] = {}

    context.close.side_effect = lambda: order.append("context.close")

    def _browser_close() -> None:
        order.append("browser.close")
        assert holder["session"].har_path == har  # already set before browser closes

    browser.close.side_effect = _browser_close
    pw.stop.side_effect = lambda: order.append("pw.stop")

    with render_session("https://example.com", record_har_path=str(har)) as s:
        holder["session"] = s

    assert order == ["context.close", "browser.close", "pw.stop"]


def test_har_path_none_when_not_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        pass

    assert s.har_path is None


# --------------------------------------------------------------------------- #
# headless launch option (#190): mirrors the fetch-tier patchright_backend fix —
# headless=True was hardcoded at this launch site too.
# --------------------------------------------------------------------------- #


def test_launches_headless_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, _context, _browser, pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com"):
        pass

    pw.chromium.launch.assert_called_once_with(headless=True)


def test_launches_headed_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, _context, _browser, pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com", headless=False):
        pass

    pw.chromium.launch.assert_called_once_with(headless=False)


# --------------------------------------------------------------------------- #
# Authenticated sessions (#200): storage_state, cookies, extra_http_headers
# --------------------------------------------------------------------------- #


def test_storage_state_reaches_new_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, _context, browser, _pw = _make_session_chain(monkeypatch)
    state = {"cookies": [], "origins": []}

    with render_session("https://example.com", storage_state=state):
        pass

    assert browser.new_context.call_args.kwargs["storage_state"] == state


def test_cookies_applied_before_new_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)
    order: list[str] = []
    context.add_cookies.side_effect = lambda *_a: order.append("add_cookies")
    context.new_page.side_effect = lambda: order.append("new_page") or context.new_page.return_value

    cookie = {"name": "session", "value": "abc", "url": "https://example.com"}
    with render_session("https://example.com", cookies=(cookie,)):
        pass

    context.add_cookies.assert_called_once_with([cookie])
    assert order == ["add_cookies", "new_page"]


def test_extra_http_headers_set_on_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com", extra_http_headers={"Authorization": "Bearer t"}):
        pass

    context.set_extra_http_headers.assert_called_once_with({"Authorization": "Bearer t"})


def test_no_extra_http_headers_call_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com"):
        pass

    context.set_extra_http_headers.assert_not_called()


def test_save_storage_state_creates_parent_dir_and_calls_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)
    target = tmp_path / "nested" / "does" / "not" / "exist" / "state.json"

    with render_session("https://example.com") as s:
        s.save_storage_state(target)

    assert target.parent.is_dir()
    context.storage_state.assert_called_once_with(path=str(target))


def test_save_storage_state_after_exit_raises_fetcherror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mirrors the #199 ordering lesson: a post-teardown call must fail loudly with a typed
    error naming the cause, not with the driver's own dead-context error."""
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        pass

    with pytest.raises(FetchError, match="save_storage_state"):
        s.save_storage_state(tmp_path / "state.json")
    context.storage_state.assert_not_called()


def test_enter_raises_fetcherror_for_missing_storage_state_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#200 review fix: a bad storage_state path must not escape as a raw FileNotFoundError,
    and must not even start the Patchright driver."""
    sync_playwright_mock = MagicMock()
    monkeypatch.setattr(_RS_MOD, "sync_playwright", sync_playwright_mock)
    missing = tmp_path / "does-not-exist.json"

    with (
        pytest.raises(FetchError, match=re.escape(str(missing))),
        render_session("https://example.com", storage_state=str(missing)),
    ):
        pass

    sync_playwright_mock.assert_not_called()


def test_enter_raises_fetcherror_for_invalid_json_storage_state_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sync_playwright_mock = MagicMock()
    monkeypatch.setattr(_RS_MOD, "sync_playwright", sync_playwright_mock)
    bad_state = tmp_path / "bad_state.json"
    bad_state.write_text("{not valid json")

    with (
        pytest.raises(FetchError, match="not valid JSON"),
        render_session("https://example.com", storage_state=str(bad_state)),
    ):
        pass

    sync_playwright_mock.assert_not_called()


# --------------------------------------------------------------------------- #
# Opt-in full network capture (#182): CDP Network-domain log, incl. SSE
# --------------------------------------------------------------------------- #


def test_network_log_empty_and_no_cdp_session_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        pass

    assert s.network_log == []
    assert s.network_log_truncated is False
    context.new_cdp_session.assert_not_called()


def test_capture_network_opens_a_cdp_session_sending_only_network_enable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)
    cdp = MagicMock(spec=pw_sync.CDPSession)
    context.new_cdp_session.return_value = cdp

    with render_session("https://example.com", capture_network=True) as s:
        assert s.network_log == []  # live list, same object the handlers would fill

    sent_methods = {c.args[0] for c in cdp.send.call_args_list}
    assert sent_methods == {"Network.enable"}


def test_capture_network_populates_network_log_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _page, context, _browser, _pw = _make_session_chain(monkeypatch)
    cdp = MagicMock(spec=pw_sync.CDPSession)
    context.new_cdp_session.return_value = cdp

    with render_session("https://example.com", capture_network=True) as s:
        handlers = {c.args[0]: c.args[1] for c in cdp.on.call_args_list}
        handlers["Network.requestWillBeSent"](
            {
                "requestId": "r1",
                "request": {"url": "https://x.test/a", "method": "GET"},
                "timestamp": 1.0,
            }
        )
        handlers["Network.eventSourceMessageReceived"](
            {"requestId": "r1", "eventName": "message", "data": "hi", "timestamp": 1.1}
        )
        # s.network_log is the SAME list the handler appends to -- visible mid-session.
        assert s.network_log[0]["url"] == "https://x.test/a"
        assert s.network_log[0]["sse_messages"][0]["data"] == "hi"

    assert s.network_log_truncated is False
