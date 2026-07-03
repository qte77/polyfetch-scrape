"""Render a dynamic (JS) page via polyfetch's playwright tier and save a screenshot.

Dogfoods the browser-tier render controls (#67/#68): ``fetch(url, tier="playwright",
render=RenderOptions(wait_until="networkidle", screenshot="viewport"))`` waits for JS/XHR
to settle, then returns the PNG on ``Response.screenshot``. No direct Patchright driving
here — the toolkit exposes it.

Run via ``make render`` or ``uv run python examples/render_screenshot.py [URL]``.
Tier-3 needs the browser binary first: ``make setup_browsers``.
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit

from polyfetch_scrape import RenderOptions, fetch

DEFAULT_URL = "https://quotes.toscrape.com/js/"
DEFAULT_OUT_DIR = Path(__file__).parent / "screenshots"


def _slug(url: str) -> str:
    """Filesystem-safe stem from a URL's host + path (e.g. quotes-toscrape-com-js)."""
    parts = urlsplit(url)
    raw = f"{parts.netloc}{parts.path}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "page"


def render(url: str, out_dir: Path) -> None:
    """Render ``url`` on the playwright tier and write ``<slug>.viewport.png``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    resp = fetch(
        url,
        tier="playwright",
        render=RenderOptions(wait_until="networkidle", screenshot="viewport"),
    )
    shot = out_dir / f"{_slug(url)}.viewport.png"

    print(f"rendered {resp.url} (status={resp.status}, backend={resp.backend})")
    if resp.screenshot is None:
        print("  no screenshot captured")
        return
    shot.write_bytes(resp.screenshot)
    print(f"  {shot.name}  {len(resp.screenshot)} bytes  -> {shot}")


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
