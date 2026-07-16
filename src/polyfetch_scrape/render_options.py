"""Browser-tier render controls, grouped into one options object for ``fetch()``."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]
ActionVerb = Literal["click", "click_text", "fill", "wait_for_selector", "wait_ms"]
ColorScheme = Literal["light", "dark", "no-preference"]


@dataclass(frozen=True, slots=True)
class RenderAction:
    """One scripted step run on the patchright tier *before* capture.

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
class Screenshot:
    """One named screenshot taken **after** the render (waits/actions have run).

    - ``target``: ``"viewport"`` or a CSS selector (element shot — must match a single
      element). ``full_page`` is unsupported (Chromium writes 0 bytes on tall pages),
      same as ``RenderOptions.screenshot``.

    Collected into ``Response.screenshots`` keyed by ``name``.
    """

    name: str
    target: str = "viewport"


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Patchright-tier controls for ``fetch(url, render=...)``.

    Ignored by the httpx / curl_cffi tiers (they don't run a browser).

    - ``wait_until``: page-load milestone before capture (``"networkidle"`` lets XHR settle).
    - ``wait_for_selector``: wait for this selector before capture.
    - ``wait_for_function``: wait until this JS predicate returns truthy (post-hydration values).
    - ``screenshot``: ``"viewport"`` or a CSS selector (element shot) → PNG bytes on
      ``Response.screenshot``. ``full_page`` is unsupported (0 bytes on tall pages).
    - ``actions``: ``RenderAction`` steps (click/fill/…) run **in order, before** the
      waits/capture — drive the page, then settle, then capture.
    - ``screenshots``: ``Screenshot(name, target)`` captures taken after the waits →
      ``Response.screenshots`` (``dict[name, PNG bytes]``); complements the single ``screenshot``.
    - ``capture_console``: collect console + uncaught-JS errors onto ``Response.console_errors``.
    - ``capture_network_failures``: collect failed requests + HTTP ``>= 400`` responses onto
      ``Response.network_failures``. Both off by default (zero overhead unless asked).
    - ``device``: a Patchright device preset name (e.g. ``"iPhone 13"``) — spreads
      ``pw.devices[device]`` (user_agent/viewport/is_mobile/...) at ``new_context()`` time.
    - ``viewport`` / ``color_scheme`` / ``user_agent`` / ``locale``: emulation set at
      ``new_context()`` time; explicit values override anything ``device`` set. These are
      also changeable post-hoc on ``.page`` for the scripting substrate (``render_session``) —
      set them here for the uniform, one-shot ``fetch()`` path.
    - ``record_video_dir`` / ``record_video_size``: record a VP8 ``.webm`` of the session into
      this directory; the finished file's path lands on ``Response.video_path``. Patchright only
      finalizes the file on ``context.close()``, so the path is unavailable until the attempt
      completes.
    """

    wait_until: WaitUntil = "domcontentloaded"
    wait_for_selector: str | None = None
    wait_for_function: str | None = None
    screenshot: str | None = None
    actions: tuple[RenderAction, ...] = ()
    screenshots: tuple[Screenshot, ...] = ()
    capture_console: bool = False
    capture_network_failures: bool = False
    viewport: tuple[int, int] | None = None
    device: str | None = None
    color_scheme: ColorScheme | None = None
    user_agent: str | None = None
    locale: str | None = None
    record_video_dir: str | Path | None = None
    record_video_size: tuple[int, int] | None = None
