"""Browser-tier render controls, grouped into one options object for ``fetch()``."""

from dataclasses import dataclass
from typing import Literal

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Playwright-tier controls for ``fetch(url, render=...)``.

    Ignored by the httpx / curl_cffi tiers (they don't run a browser).

    - ``wait_until``: page-load milestone before capture (``"networkidle"`` lets XHR settle).
    - ``wait_for_selector``: wait for this selector before capture.
    - ``wait_for_function``: wait until this JS predicate returns truthy (post-hydration values).
    - ``screenshot``: ``"viewport"`` or a CSS selector (element shot) → PNG bytes on
      ``Response.screenshot``. ``full_page`` is unsupported (0 bytes on tall pages).
    """

    wait_until: WaitUntil = "domcontentloaded"
    wait_for_selector: str | None = None
    wait_for_function: str | None = None
    screenshot: str | None = None
