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


def _fake_logged_request(
    url: str,
    method: str = "GET",
    *,
    status: int | None = 200,
    response_end: float | None = 9.0,
) -> MagicMock:
    """A patchright Request as seen by requestfinished/requestfailed handlers."""
    req = MagicMock()
    req.url = url
    req.method = method
    response = None
    if status is not None:
        response = MagicMock()
        response.status = status
    req.response.return_value = response
    req.timing = {"startTime": 1.0, "responseEnd": response_end} if response_end is not None else {}
    return req


def test_network_log_opt_in_records_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com", capture_network_log=True) as s:
        _handlers(page)["requestfinished"](_fake_logged_request("https://x/ok"))
        # Two "requestfailed" listeners are live here (failure capture + full log), and
        # _handlers keeps only the last — fire every one so the assertion is order-agnostic.
        dead = _fake_logged_request("https://x/dead", status=None, response_end=None)
        for call in page.on.call_args_list:
            if call.args[0] == "requestfailed":
                call.args[1](dead)

    assert s.network_log == [
        {"url": "https://x/ok", "method": "GET", "status": 200, "duration_ms": 9.0},
        {"url": "https://x/dead", "method": "GET", "status": None, "duration_ms": None},
    ]


def test_network_log_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        # Console + failure capture stay always-on; only the full log is gated.
        registered = {c.args[0] for c in page.on.call_args_list}
        assert "requestfinished" not in registered
        assert {"console", "pageerror", "requestfailed", "response"} <= registered

    assert s.network_log == []


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


def test_video_path_none_when_not_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    page, *_ = _make_session_chain(monkeypatch)

    with render_session("https://example.com") as s:
        pass

    assert s.video_path is None
    page.video.path.assert_not_called()
