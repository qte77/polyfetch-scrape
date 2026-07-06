"""Browser-tier render controls, grouped into one options object for ``fetch()``."""

from dataclasses import dataclass
from typing import Literal

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]
ActionVerb = Literal["click", "click_text", "fill", "wait_for_selector", "wait_ms"]


@dataclass(frozen=True, slots=True)
class RenderAction:
    """One scripted step run on the playwright tier *before* capture.

    - ``click`` (selector) / ``click_text`` (text): click an element.
    - ``fill`` (selector, value): type ``value`` into an input.
    - ``wait_for_selector`` (selector): block until the selector appears.
    - ``wait_ms`` (ms): fixed pause, for SPAs that settle on a timer.
    """

    verb: ActionVerb
    selector: str | None = None
    text: str | None = None
    value: str | None = None
    ms: int | None = None


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Playwright-tier controls for ``fetch(url, render=...)``.

    Ignored by the httpx / curl_cffi tiers (they don't run a browser).

    - ``wait_until``: page-load milestone before capture (``"networkidle"`` lets XHR settle).
    - ``wait_for_selector``: wait for this selector before capture.
    - ``wait_for_function``: wait until this JS predicate returns truthy (post-hydration values).
    - ``screenshot``: ``"viewport"`` or a CSS selector (element shot) → PNG bytes on
      ``Response.screenshot``. ``full_page`` is unsupported (0 bytes on tall pages).
    - ``actions``: ``RenderAction`` steps (click/fill/…) run **in order, before** the
      waits/capture — drive the page, then settle, then capture.
    """

    wait_until: WaitUntil = "domcontentloaded"
    wait_for_selector: str | None = None
    wait_for_function: str | None = None
    screenshot: str | None = None
    actions: tuple[RenderAction, ...] = ()
