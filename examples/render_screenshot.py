"""Render a dynamic (JS) page with Patchright/Chromium and save screenshots.

Direct-drive stop-gap for screenshots polyfetch's tiers don't yet expose
(first-class screenshots = #68; tier-3 wait strategies = #67/#70). Mirrors the
launch pattern of ``examples/fallback_tiers_demo.py``'s ``demo_tier_3``.

Run via ``make render`` or ``uv run python examples/render_screenshot.py [URL]``.
Tier-3 needs the browser binary first: ``make setup_browsers``.

``wait_until="networkidle"`` lets the page's JS/XHR settle before capture, which
is what a dynamic page needs. Each run writes two PNGs under ``--out-dir``: a
full-page shot and a viewport shot.
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = "https://quotes.toscrape.com/js/"
DEFAULT_OUT_DIR = Path(__file__).parent / "screenshots"


def _slug(url: str) -> str:
    """Filesystem-safe stem from a URL's host + path (e.g. quotes-toscrape-com-js)."""
    parts = urlsplit(url)
    raw = f"{parts.netloc}{parts.path}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "page"


def render(url: str, out_dir: Path) -> None:
    """Render ``url`` and write ``<slug>.full.png`` + ``<slug>.viewport.png``."""
    from patchright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(url)
    full = out_dir / f"{slug}.full.png"
    viewport = out_dir / f"{slug}.viewport.png"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            response = page.goto(url, wait_until="networkidle")
            status = response.status if response is not None else None
            title = page.title()
            page.screenshot(path=str(full), full_page=True)
            page.screenshot(path=str(viewport), full_page=False)
            print(f"rendered {page.url} (status={status}, title={title!r})")
            for shot in (full, viewport):
                print(f"  {shot.name}  {shot.stat().st_size} bytes  -> {shot}")
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a JS page and screenshot it.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="page to render")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="screenshot output directory"
    )
    args = parser.parse_args()
    render(args.url, args.out_dir)


if __name__ == "__main__":
    main()
