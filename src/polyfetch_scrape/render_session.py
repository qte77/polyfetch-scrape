"""Managed, headless-but-interactive Patchright session for multi-step SPA flows.

The browser tier's ``fetch(url, render=...)`` is single-shot: one linear
``RenderOptions(actions=...)`` sequence, one capture, teardown. A genuine
interactive flow (act → assert → act, branch on the DOM) needs a live ``Page``.
``render_session`` provides that as a context manager, reusing the browser tier's
console/network capture and screenshot helpers, so consumers stop re-hand-rolling
raw Patchright launch/teardown/capture boilerplate.

Chromium-only (headless), consistent with the patchright fetch tier.

NOTE: like the fetch-tier capture, ``console_errors`` / ``network_failures``
reflect only THIS process's network — a cross-origin failure a real user hits
(CORS / extension / proxy) can succeed here and read clean.
"""

import contextlib
from pathlib import Path
from typing import Any

from patchright.sync_api import TimeoutError as PwTimeoutError
from patchright.sync_api import sync_playwright

from polyfetch_scrape._backends.patchright_backend import (
    attach_capture,
    capture_screenshot,
    context_kwargs,
)
from polyfetch_scrape._platform import ensure_browser_tier_supported
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_options import (
    ColorScheme,
    HarContent,
    HarMode,
    RenderOptions,
    WaitUntil,
)


class RenderSession:
    """A live managed ``Page`` with act→assert→act methods; use via :func:`render_session`.

    Console + network-failure capture is always on (``console_errors`` /
    ``network_failures``); ``shot(name)`` collects named PNG bytes into ``screenshots``.
    On an exception inside the ``with`` block a ``"exception"`` screenshot is captured
    before teardown.
    """

    def __init__(
        self,
        url: str,
        *,
        wait_until: WaitUntil = "domcontentloaded",
        timeout: float = 30.0,
        device: str | None = None,
        viewport: tuple[int, int] | None = None,
        color_scheme: ColorScheme | None = None,
        user_agent: str | None = None,
        locale: str | None = None,
        record_video_dir: str | Path | None = None,
        record_video_size: tuple[int, int] | None = None,
        record_har_path: str | Path | None = None,
        record_har_mode: HarMode = "minimal",
        record_har_content: HarContent = "omit",
    ) -> None:
        self._url = url
        self._wait_until = wait_until
        self._timeout_ms = int(timeout * 1000)
        self._opts = RenderOptions(
            capture_console=True,
            capture_network_failures=True,
            device=device,
            viewport=viewport,
            color_scheme=color_scheme,
            user_agent=user_agent,
            locale=locale,
            record_video_dir=record_video_dir,
            record_video_size=record_video_size,
            record_har_path=record_har_path,
            record_har_mode=record_har_mode,
            record_har_content=record_har_content,
        )
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._video: Any = None
        self.page: Any = None
        self.video_path: Path | None = None
        self.har_path: Path | None = None
        self.screenshots: dict[str, bytes] = {}
        self.console_errors: list[str] = []
        self.network_failures: list[dict[str, object]] = []

    def __enter__(self) -> "RenderSession":
        # Same platform gate as the fetch tier: no musllinux patchright wheel (#197).
        ensure_browser_tier_supported()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(**context_kwargs(self._pw, self._opts))
        self.page = self._context.new_page()
        # Raw `s.page` calls (e.g. `.locator(...).click()`) otherwise fall back to Playwright's
        # own 30000ms default regardless of this session's `timeout=` (#216) — align both page-
        # level defaults so `.page` and the RenderSession convenience methods agree.
        self.page.set_default_timeout(self._timeout_ms)
        self.page.set_default_navigation_timeout(self._timeout_ms)
        self.console_errors, self.network_failures = attach_capture(self.page, self._opts)
        self._video = self.page.video if self._opts.record_video_dir is not None else None
        try:
            self.page.goto(self._url, wait_until=self._wait_until, timeout=self._timeout_ms)
        except PwTimeoutError as exc:
            self._teardown()
            raise FetchError(f"render_session: navigation timed out: {self._url}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is not None:
            self._safe_shot("exception")
        self._teardown()
        return False

    def click(self, selector: str) -> None:
        self.page.click(selector, timeout=self._timeout_ms)

    def click_text(self, text: str) -> None:
        self.page.get_by_text(text).click(timeout=self._timeout_ms)

    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value, timeout=self._timeout_ms)

    def submit(self) -> None:
        """Press Enter on the focused element (submit a composer / form input)."""
        self.page.keyboard.press("Enter")

    def wait_for_selector(self, selector: str) -> None:
        self.page.wait_for_selector(selector, timeout=self._timeout_ms)

    def wait_for_function(self, expression: str) -> None:
        self.page.wait_for_function(expression, timeout=self._timeout_ms)

    def wait_ms(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)

    def shot(self, name: str) -> bytes:
        """Capture a viewport PNG, store it under ``name`` in ``screenshots``, return the bytes."""
        data = capture_screenshot(self.page, "viewport") or b""
        self.screenshots[name] = data
        return data

    def _safe_shot(self, name: str) -> None:
        with contextlib.suppress(Exception):
            self.screenshots[name] = capture_screenshot(self.page, "viewport") or b""

    def _teardown(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.close()
        # Patchright only finalizes the video/HAR once its context has closed (above). The
        # video path needs a live driver connection to resolve (video.path()), while the HAR
        # path is already known (record_har_path is the exact destination) but the file itself
        # isn't flushed to disk until context.close() completes — so read/set both here, before
        # the browser and driver are torn down (mirrors `_finalize_video` / `_finalize_har` in
        # `_backends/patchright_backend.py`). Reading the video path after `pw.stop()` (the bug
        # in #199) made the call raise against the dead driver, silently swallowed by suppress.
        if self._video is not None:
            with contextlib.suppress(Exception):
                self.video_path = Path(self._video.path())
        if self._opts.record_har_path is not None:
            self.har_path = Path(self._opts.record_har_path)
        for obj, method in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                with contextlib.suppress(Exception):
                    getattr(obj, method)()


def render_session(
    url: str,
    *,
    wait_until: WaitUntil = "domcontentloaded",
    timeout: float = 30.0,
    device: str | None = None,
    viewport: tuple[int, int] | None = None,
    color_scheme: ColorScheme | None = None,
    user_agent: str | None = None,
    locale: str | None = None,
    record_video_dir: str | Path | None = None,
    record_video_size: tuple[int, int] | None = None,
    record_har_path: str | Path | None = None,
    record_har_mode: HarMode = "minimal",
    record_har_content: HarContent = "omit",
) -> RenderSession:
    """Open a managed headless Patchright session for an interactive multi-step flow.

    ``device``/``viewport``/``color_scheme``/``user_agent``/``locale`` set emulation at
    ``new_context()`` time (mirrors ``RenderOptions``). ``viewport`` is a plain
    ``(width, height)`` pixel tuple, e.g. ``(1280, 720)`` — not a ``RenderOptions``/dict.
    ``record_video_dir`` (+ optional ``record_video_size``, also a ``(width, height)`` tuple)
    records a VP8 ``.webm``; the finished path lands on ``RenderSession.video_path`` once the
    ``with`` block exits (Patchright finalizes the file on context close, not before).

    ``record_har_path`` (+ optional ``record_har_mode``, ``record_har_content``) records a
    HAR 1.2 file of every request the session makes, at that exact path; it lands on
    ``RenderSession.har_path`` once the ``with`` block exits (same context-close timing as the
    video). Defaults to ``"minimal"`` mode and ``"omit"`` content (no response bodies).
    **Security:** a HAR records every request/response header, including ``Cookie`` and
    ``Authorization`` — treat it as a credentials-bearing artifact once an authenticated
    session is in play.

    ``timeout`` (seconds) is applied both to the ``RenderSession`` convenience methods
    (``click``, ``fill``, ``wait_for_selector``, ...) and, via ``page.set_default_timeout`` /
    ``set_default_navigation_timeout``, to raw calls on ``s.page`` — so a direct
    ``s.page.locator(...).click()`` honors the same budget instead of Playwright's own
    30000ms default.

    Use as a context manager::

        with render_session(url) as s:
            s.click_text("Live")
            s.wait_for_selector("input:not([disabled])")
            s.fill("input", "hello"); s.submit()
            s.shot("after")
        # auto: console/network capture on s.console_errors / s.network_failures,
        #       screenshot-on-exception, teardown, s.video_path / s.har_path if recording.
    """
    return RenderSession(
        url,
        wait_until=wait_until,
        timeout=timeout,
        device=device,
        viewport=viewport,
        color_scheme=color_scheme,
        user_agent=user_agent,
        locale=locale,
        record_video_dir=record_video_dir,
        record_video_size=record_video_size,
        record_har_path=record_har_path,
        record_har_mode=record_har_mode,
        record_har_content=record_har_content,
    )
