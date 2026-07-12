"""Regenerate the README screencast GIF — polyfetch navigating a website.

Showcases the public `render_session` API driving a headless browser through a real
multi-step site navigation (browse pagination -> open the login form -> fill it ->
submit -> land logged-in), capturing one screenshot per step via `s.shot(...)` and
assembling the frames into `assets/usage.gif` with Pillow.

Target is `quotes.toscrape.com` — a purpose-built, ToS-safe scraping sandbox. This
uses only polyfetch's public surface (no raw Patchright driving); the same walk is
what a consumer would write to automate a site.

Deterministic + reproducible — re-run on any change instead of hand-capturing. Needs
the browser binary (`make setup_browsers`) and Pillow (added ephemerally by the recipe):

    make screencast   # uv run --with pillow python examples/navigate_screencast.py
"""

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image

from polyfetch_scrape import render_session

TARGET = "https://quotes.toscrape.com/"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "assets" / "usage.gif"
GIF_WIDTH = 1000  # downscale for a lighter README asset
FRAME_MS = 1600  # per-frame hold in the looping GIF


def _frame(png: bytes, frames: list[Image.Image]) -> None:
    if not png:
        return
    img = Image.open(BytesIO(png)).convert("RGB")
    if img.width != GIF_WIDTH:
        img = img.resize((GIF_WIDTH, round(img.height * GIF_WIDTH / img.width)))
    frames.append(img)


def _walk() -> list[Image.Image]:
    """Drive quotes.toscrape.com through a multi-step navigation, one frame per step."""
    frames: list[Image.Image] = []
    with render_session(TARGET, wait_until="networkidle") as s:
        s.wait_for_selector(".quote")
        _frame(s.shot("home"), frames)  # page 1

        s.click("li.next a")  # paginate
        s.wait_for_selector(".quote")
        _frame(s.shot("page2"), frames)  # page 2

        s.click('a[href="/login"]')  # open the login form
        s.wait_for_selector("#username")
        _frame(s.shot("login"), frames)

        s.fill("#username", "demo")  # fill credentials
        s.fill("#password", "demo")
        _frame(s.shot("filled"), frames)

        s.submit()  # submit -> logged in
        s.wait_for_selector('a[href="/logout"]')
        _frame(s.shot("loggedin"), frames)
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="Record the README navigation screencast GIF.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output GIF path")
    args = parser.parse_args()

    frames = _walk()
    if not frames:
        print("no frames captured")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.out,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
    )
    print(f"wrote {args.out} ({len(frames)} frames, {args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
