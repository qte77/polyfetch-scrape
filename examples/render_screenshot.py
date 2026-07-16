"""Render a dynamic (JS) page via polyfetch's patchright tier and save a screenshot.

Dogfoods the browser-tier render controls (#67/#68): ``fetch(url, tier="patchright",
render=RenderOptions(wait_until="networkidle", screenshot="viewport"))`` waits for JS/XHR
to settle, then returns the PNG on ``Response.screenshot``. No direct Patchright driving
here — the toolkit exposes it.

Also demoes the emulation/video ``RenderOptions`` fields shipped in v0.7.0 (#162):
``--device`` (Patchright device preset), ``--color-scheme`` (prefers-color-scheme), and
``--video-out`` (record a ``.webm`` of the session to ``Response.video_path``).

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


def render(
    url: str,
    out_dir: Path,
    *,
    device: str | None = None,
    color_scheme: str | None = None,
    video_out: Path | None = None,
) -> None:
    """Render ``url`` on the patchright tier and write ``<slug>.viewport.png``.

    ``device``/``color_scheme`` emulate a device preset / prefers-color-scheme at
    context creation; ``video_out`` (if given) records the session to a ``.webm``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if video_out is not None:
        video_out.mkdir(parents=True, exist_ok=True)
    resp = fetch(
        url,
        tier="patchright",
        render=RenderOptions(
            wait_until="networkidle",
            screenshot="viewport",
            device=device,
            color_scheme=color_scheme,
            record_video_dir=video_out,
        ),
    )
    shot = out_dir / f"{_slug(url)}.viewport.png"

    print(f"rendered {resp.url} (status={resp.status}, backend={resp.backend})")
    if resp.screenshot is None:
        print("  no screenshot captured")
    else:
        shot.write_bytes(resp.screenshot)
        print(f"  {shot.name}  {len(resp.screenshot)} bytes  -> {shot}")

    if video_out is not None:
        if resp.video_path is not None:
            print(f"  video -> {resp.video_path}")
        else:
            print("  no video recorded")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a JS page and screenshot it.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="page to render")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="screenshot output directory"
    )
    parser.add_argument(
        "--device", default=None, help='Patchright device preset to emulate (e.g. "iPhone 13")'
    )
    parser.add_argument(
        "--color-scheme",
        choices=["light", "dark"],
        default=None,
        help="emulate prefers-color-scheme",
    )
    parser.add_argument(
        "--video-out", type=Path, default=None, help="directory to record a .webm session video"
    )
    args = parser.parse_args()
    render(
        args.url,
        args.out_dir,
        device=args.device,
        color_scheme=args.color_scheme,
        video_out=args.video_out,
    )


if __name__ == "__main__":
    main()
