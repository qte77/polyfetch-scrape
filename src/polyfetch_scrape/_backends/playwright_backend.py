import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from patchright.sync_api import TimeoutError as PwTimeoutError
from patchright.sync_api import sync_playwright

from polyfetch_scrape._backends import (
    FingerprintBlock,
    permanent_redirect_target,
    raise_for_terminal_status,
)
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

_FINGERPRINT_STATUSES: frozenset[int] = frozenset({403})


@dataclass(frozen=True, slots=True)
class _Attempt:
    response: Response | None
    block_status: int | None
    error: Exception | None


def attempt(
    method: str,
    url: str,
    headers: Mapping[str, str] | None,
    timeout: float,
    policy: RetryPolicy,
    wait_for_selector: str | None = None,
    screenshot: str | None = None,
) -> Response:
    if method.upper() != "GET":
        raise FetchError(f"playwright backend supports GET only, not {method}")

    last = _Attempt(None, None, None)
    timeout_ms = int(timeout * 1000)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for attempt_idx in range(policy.max_attempts):
                last = _attempt_once(
                    browser, url, headers, timeout_ms, wait_for_selector, screenshot
                )
                if last.response is not None:
                    return last.response
                if attempt_idx + 1 < policy.max_attempts:
                    time.sleep(policy.backoff_initial * (policy.backoff_factor**attempt_idx))
        finally:
            browser.close()

    detail = (
        f"status={last.block_status}" if last.block_status is not None else f"error={last.error!r}"
    )
    msg = f"playwright fetch failed after {policy.max_attempts} attempts ({detail}): {url}"
    if last.block_status in _FINGERPRINT_STATUSES:
        raise FingerprintBlock(msg) from last.error
    raise FetchError(msg) from last.error


def _attempt_once(
    browser: Any,
    url: str,
    headers: Mapping[str, str] | None,
    timeout_ms: int,
    wait_for_selector: str | None,
    screenshot: str | None,
) -> _Attempt:
    context = browser.new_context()
    if headers:
        context.set_extra_http_headers(dict(headers))
    page = context.new_page()
    try:
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PwTimeoutError as exc:
            return _Attempt(None, None, exc)

        if response is None:
            return _Attempt(None, None, FetchError("playwright: no response object"))

        status = int(response.status)
        if status in _FINGERPRINT_STATUSES:
            return _Attempt(None, status, None)

        raise_for_terminal_status(status, url)

        if wait_for_selector is not None:
            page.wait_for_selector(wait_for_selector, timeout=timeout_ms)

        body = page.content().encode("utf-8")
        all_headers = {str(k): str(v) for k, v in dict(response.all_headers()).items()}
        return _Attempt(
            Response(
                url=str(page.url),
                status=status,
                headers=all_headers,
                body=body,
                content_type=all_headers.get("content-type"),
                backend="playwright",
                permanent_redirect_to=permanent_redirect_target(status, all_headers),
                screenshot=_capture_screenshot(page, screenshot),
            ),
            None,
            None,
        )
    finally:
        context.close()


def _capture_screenshot(page: Any, target: str | None) -> bytes | None:
    """Capture a PNG: ``"viewport"`` shot, or an element shot for a CSS selector.

    ``full_page`` is intentionally unsupported — Chromium writes 0 bytes on very
    tall pages; use ``"viewport"`` or an element selector instead.
    """
    if target is None:
        return None
    if target == "viewport":
        return page.screenshot()
    return page.locator(target).screenshot()
