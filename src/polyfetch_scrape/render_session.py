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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from patchright.sync_api import TimeoutError as PwTimeoutError
from patchright.sync_api import sync_playwright

from polyfetch_scrape._backends.patchright_backend import (
    attach_capture,
    capture_screenshot,
    context_kwargs,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_options import ColorScheme, RenderOptions, WaitUntil


class RenderSession:
    """A live managed ``Page`` with act→assert→act methods; use via :func:`render_session`.

    Console + network-failure capture is always on (``console_errors`` /
    ``network_failures``); ``shot(name)`` collects named PNG bytes into ``screenshots``.
    On an exception inside the ``with`` block a ``"exception"`` screenshot is captured
    before teardown. ``storage_state`` restores a saved login; ``save_storage_state(path)``
    writes the current one back out.
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
        storage_state: str | Path | Mapping[str, Any] | None = None,
        extra_http_headers: Mapping[str, str] | None = None,
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
            storage_state=storage_state,
            extra_http_headers=extra_http_headers,
        )
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._video: Any = None
        self.page: Any = None
        self.video_path: Path | None = None
        self.screenshots: dict[str, bytes] = {}
        self.console_errors: list[str] = []
        self.network_failures: list[dict[str, object]] = []

    def __enter__(self) -> "RenderSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(**context_kwargs(self._pw, self._opts))
        self.page = self._context.new_page()
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

    def save_storage_state(self, path: str | Path) -> Path:
        """Write the context's cookies + localStorage to ``path``; return that path.

        Feed the file back as ``render_session(..., storage_state=path)`` on the next run to
        start logged in. Call this **inside** the ``with`` block — teardown closes the context
        and the state goes with it.
        """
        if self._context is None:
            raise FetchError(
                "save_storage_state: no live context — call it inside the `with` block"
            )
        dest = Path(path)
        # Playwright creates parent dirs for screenshot/pdf/video paths but NOT for
        # storage_state — a missing dir raises FileNotFoundError *after* a successful
        # login, destroying the session we just paid for. Create it here to match the
        # behaviour the rest of the API already has.
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(dest))
        return dest

    def _safe_shot(self, name: str) -> None:
        with contextlib.suppress(Exception):
            self.screenshots[name] = capture_screenshot(self.page, "viewport") or b""

    def _teardown(self) -> None:
        for obj, method in ((self._context, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                with contextlib.suppress(Exception):
                    getattr(obj, method)()
        # Drop the closed context so save_storage_state() fails loudly instead of erroring
        # deep inside a dead driver.
        self._context = None
        # The video file is only finalized once its context has closed (above), so read
        # the path last — after the loop, regardless of browser/pw teardown outcome.
        if self._video is not None:
            with contextlib.suppress(Exception):
                self.video_path = Path(self._video.path())


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
    storage_state: str | Path | Mapping[str, Any] | None = None,
    extra_http_headers: Mapping[str, str] | None = None,
) -> RenderSession:
    """Open a managed headless Patchright session for an interactive multi-step flow.

    ``device``/``viewport``/``color_scheme``/``user_agent``/``locale`` set emulation at
    ``new_context()`` time (mirrors ``RenderOptions``). ``record_video_dir`` (+ optional
    ``record_video_size``) records a VP8 ``.webm``; the finished path lands on
    ``RenderSession.video_path`` once the ``with`` block exits (Patchright finalizes the
    file on context close, not before).

    ``storage_state`` (a saved storage-state JSON path, or the equivalent mapping) restores
    cookies + localStorage, so the session starts authenticated; ``extra_http_headers``
    (mirrors ``fetch(headers=...)``) go on every request the context makes. Persist a fresh
    login for the next run with ``s.save_storage_state(path)`` — recipe in
    ``docs/scripting.md`` ("Authenticated session").

    Use as a context manager::

        with render_session(url) as s:
            s.click_text("Live")
            s.wait_for_selector("input:not([disabled])")
            s.fill("input", "hello"); s.submit()
            s.shot("after")
        # auto: console/network capture on s.console_errors / s.network_failures,
        #       screenshot-on-exception, teardown, s.video_path if recording.
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
        storage_state=storage_state,
        extra_http_headers=extra_http_headers,
    )
