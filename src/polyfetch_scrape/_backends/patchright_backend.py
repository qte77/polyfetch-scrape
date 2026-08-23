import contextlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any

from patchright.sync_api import TimeoutError as PwTimeoutError
from patchright.sync_api import sync_playwright

from polyfetch_scrape._backends import (
    FingerprintBlock,
    permanent_redirect_target,
    raise_for_terminal_status,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_options import RenderAction, RenderOptions
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, next_delay, parse_retry_after, should_retry

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: Response | None
    block_status: int | None
    error: Exception | None
    retry_after: float | None = None


@dataclass(frozen=True, slots=True)
class Capture:
    """The still-filling sinks registered by :func:`attach_capture` (empty when opted out)."""

    console_errors: list[str]
    network_failures: list[dict[str, object]]
    network_log: list[dict[str, object]]


def attempt(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    render: RenderOptions | None = None,
) -> Response:
    if method.upper() != "GET":
        raise FetchError(f"patchright backend supports GET only, not {method}")

    opts = render if render is not None else RenderOptions()
    last = _Attempt(None, None, None)
    timeout_ms = int(timeout * 1000)

    with sync_playwright() as pw:
        ctx_kwargs = context_kwargs(pw, opts)
        browser = pw.chromium.launch(headless=True)
        try:
            for attempt_idx in range(policy.max_attempts):
                last = _attempt_once(browser, url, headers, timeout_ms, opts, ctx_kwargs, policy)
                if last.response is not None:
                    return last.response
                if attempt_idx + 1 < policy.max_attempts:
                    time.sleep(next_delay(last.retry_after, policy, attempt_idx))
        finally:
            browser.close()

    detail = (
        f"status={last.block_status}" if last.block_status is not None else f"error={last.error!r}"
    )
    msg = f"patchright fetch failed after {policy.max_attempts} attempts ({detail}): {url}"
    if last.block_status in _FINGERPRINT_STATUSES:
        raise FingerprintBlock(msg) from last.error
    raise FetchError(msg) from last.error


def context_kwargs(pw: Any, opts: RenderOptions) -> dict[str, Any]:
    """Build browser.new_context(**kwargs) from RenderOptions emulation/video fields.

    Device preset first (a bundle of user_agent/viewport/is_mobile/...), then explicit
    fields override it. record_video_* map to Patchright's {width,height} shape.
    """
    kwargs: dict[str, Any] = {}
    if opts.device is not None:
        kwargs.update(
            pw.devices[opts.device]
        )  # spread directly — new_context accepts default_browser_type
    if opts.viewport is not None:
        kwargs["viewport"] = {"width": opts.viewport[0], "height": opts.viewport[1]}
    if opts.user_agent is not None:
        kwargs["user_agent"] = opts.user_agent
    if opts.locale is not None:
        kwargs["locale"] = opts.locale
    if opts.color_scheme is not None:
        kwargs["color_scheme"] = opts.color_scheme
    if opts.record_video_dir is not None:
        kwargs["record_video_dir"] = str(opts.record_video_dir)
        if opts.record_video_size is not None:
            kwargs["record_video_size"] = {
                "width": opts.record_video_size[0],
                "height": opts.record_video_size[1],
            }
    return kwargs


def _attempt_once(
    browser: Any,
    url: str,
    headers: Mapping[str, str] | None,
    timeout_ms: int,
    opts: RenderOptions,
    context_kwargs: dict[str, Any],
    policy: RetryPolicy,
) -> _Attempt:
    context = browser.new_context(**context_kwargs)
    if headers:
        context.set_extra_http_headers(dict(headers))
    page = context.new_page()
    capture = attach_capture(page, opts)
    video = page.video if opts.record_video_dir is not None else None
    try:
        try:
            result = _run_page(page, url, timeout_ms, opts, policy, capture)
        finally:
            context.close()
    except Exception:
        # A terminal status (raise_for_terminal_status) or any other error escaped _run_page.
        # The context is already closed, so Patchright has finalized the video on disk — no
        # success Response will reference it, so delete the orphan before propagating.
        _discard_video(video)
        raise
    return _finalize_video(result, video)


def _run_page(
    page: Any,
    url: str,
    timeout_ms: int,
    opts: RenderOptions,
    policy: RetryPolicy,
    capture: Capture,
) -> _Attempt:
    """Navigate, check status/retry conditions, run actions/waits, and build the ``_Attempt``."""
    try:
        response = page.goto(url, wait_until=opts.wait_until, timeout=timeout_ms)
    except PwTimeoutError as exc:
        return _Attempt(None, None, exc)

    if response is None:
        return _Attempt(None, None, FetchError("patchright: no response object"))

    status = int(response.status)
    if should_retry(status, policy) or status in _FINGERPRINT_STATUSES:
        headers_map = {str(k).lower(): str(v) for k, v in dict(response.all_headers()).items()}
        return _Attempt(None, status, None, parse_retry_after(headers_map.get("retry-after")))

    raise_for_terminal_status(status, url)
    _apply_actions(page, opts.actions, timeout_ms)
    _apply_waits(page, opts, timeout_ms)

    body = page.content().encode("utf-8")
    all_headers = {str(k): str(v) for k, v in dict(response.all_headers()).items()}
    screenshots = {s.name: capture_screenshot(page, s.target) or b"" for s in opts.screenshots}
    return _Attempt(
        Response(
            url=str(page.url),
            status=status,
            headers=all_headers,
            body=body,
            content_type=all_headers.get("content-type"),
            backend="patchright",
            permanent_redirect_to=permanent_redirect_target(status, all_headers),
            screenshot=capture_screenshot(page, opts.screenshot),
            console_errors=capture.console_errors,
            network_failures=capture.network_failures,
            network_log=capture.network_log,
            screenshots=screenshots,
        ),
        None,
        None,
    )


def _finalize_video(result: _Attempt, video: Any) -> _Attempt:
    """Attach the finished video path to a success response, or delete it on failure.

    Patchright only writes the video file on ``context.close()``, so this must run
    AFTER close (``_attempt_once`` calls it once the context is closed).
    """
    if video is None:
        return result
    if result.response is not None:
        path = Path(video.path())
        return replace(result, response=replace(result.response, video_path=path))
    _discard_video(video)
    return result


def _discard_video(video: Any) -> None:
    """Delete a recorded video that no successful ``Response`` will reference (best-effort)."""
    if video is not None:
        with contextlib.suppress(Exception):
            video.delete()


def _record_console(msg: Any, sink: list[str]) -> None:
    if msg.type == "error":
        sink.append(str(msg.text))


def _record_pageerror(err: Any, sink: list[str]) -> None:
    sink.append(str(err))


def _record_request_failure(req: Any, sink: list[dict[str, object]]) -> None:
    sink.append({"url": str(req.url), "error": str(req.failure)})


def _record_bad_response(resp: Any, sink: list[dict[str, object]]) -> None:
    if int(resp.status) >= 400:
        sink.append({"url": str(resp.url), "status": int(resp.status)})


def _request_duration_ms(req: Any) -> float | None:
    """Request start → ``responseEnd`` in ms, or None when the browser reported no timing.

    Patchright's ``request.timing`` gives ``startTime`` as an epoch stamp and every later
    marker as an offset from it, using ``-1`` for "not measured" — so ``responseEnd`` IS the
    duration once it is non-negative.
    """
    with contextlib.suppress(Exception):
        end = float(dict(req.timing).get("responseEnd", -1))
        if end >= 0:
            return end
    return None


def _record_network_entry(req: Any, sink: list[dict[str, object]]) -> None:
    """Append one completed request (finished OR failed) to the full network log."""
    response = None
    with contextlib.suppress(Exception):
        response = req.response()
    sink.append(
        {
            "url": str(req.url),
            "method": str(req.method),
            "status": int(response.status) if response is not None else None,
            "duration_ms": _request_duration_ms(req),
        }
    )


def attach_capture(page: Any, opts: RenderOptions) -> Capture:
    """Register opt-in console/network listeners; return the (still-filling) capture sinks.

    A headless capture reflects only THIS process's network — a cross-origin failure a real user
    hits (CORS / extension / proxy) can succeed here and read clean. Force a known failure to
    trust it (AGENT_LEARNINGS: "Headless console/network capture only reflects the runner's own
    network").
    """
    capture = Capture(console_errors=[], network_failures=[], network_log=[])
    if opts.capture_console:
        page.on("console", partial(_record_console, sink=capture.console_errors))
        page.on("pageerror", partial(_record_pageerror, sink=capture.console_errors))
    if opts.capture_network_failures:
        page.on("requestfailed", partial(_record_request_failure, sink=capture.network_failures))
        page.on("response", partial(_record_bad_response, sink=capture.network_failures))
    if opts.capture_network_log:
        # Both terminal request events — a failed request never fires "requestfinished", so
        # listening to only one would silently drop half the trace.
        page.on("requestfinished", partial(_record_network_entry, sink=capture.network_log))
        page.on("requestfailed", partial(_record_network_entry, sink=capture.network_log))
    return capture


def _apply_actions(page: Any, actions: tuple[RenderAction, ...], timeout_ms: int) -> None:
    """Run scripted actions in order before waiting/capture (drive → settle → capture)."""
    for action in actions:
        if action.verb == "click":
            page.click(action.selector, timeout=timeout_ms)
        elif action.verb == "click_text":
            page.get_by_text(action.text).click(timeout=timeout_ms)
        elif action.verb == "fill":
            page.fill(action.selector, action.value, timeout=timeout_ms)
        elif action.verb == "wait_for_selector":
            page.wait_for_selector(action.selector, timeout=timeout_ms)
        elif action.verb == "wait_ms":
            page.wait_for_timeout(action.ms)


def _apply_waits(page: Any, opts: RenderOptions, timeout_ms: int) -> None:
    """Wait for a selector and/or a JS predicate before capture (both optional)."""
    if opts.wait_for_selector is not None:
        page.wait_for_selector(opts.wait_for_selector, timeout=timeout_ms)
    if opts.wait_for_function is not None:
        page.wait_for_function(opts.wait_for_function, timeout=timeout_ms)


def capture_screenshot(page: Any, target: str | None) -> bytes | None:
    """Capture a PNG: ``"viewport"``, ``"full_page"``, or an element shot for a CSS selector.

    ``"full_page"`` captures the whole scrollable page (patchright >= 1.61.2 writes the
    full image; older builds wrote 0 bytes on very tall pages). On an ``is_mobile``
    emulated device it clips to the viewport rather than scrolling.
    """
    if target is None:
        return None
    if target == "viewport":
        return page.screenshot()
    if target == "full_page":
        return page.screenshot(full_page=True)
    return page.locator(target).screenshot()
