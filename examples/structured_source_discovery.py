"""Discover a site's structured entrypoints via polyfetch's fetch-layer discovery.

Reports the cheaper-than-HTML entrypoints a site advertises — sitemaps (incl. event
variants), RSS/Atom/iCal feeds, ``llms.txt``, and embedded JSON-LD ``@type`` values —
so a downstream consumer can parse structured data instead of LLM-scraping the page.
Discovery stops at the entrypoints; it does not fetch or extract the content behind them.

Run via ``make discover URL=https://...`` or
``uv run python examples/structured_source_discovery.py [URL]``.
"""

import argparse
from dataclasses import asdict

from polyfetch_scrape.utils.discovery import discover

DEFAULT_URL = "https://10times.com/"


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover a site's structured entrypoints.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="site URL / origin to probe")
    args = parser.parse_args()

    found = discover(args.url)
    print(found.url)
    for name, values in asdict(found).items():
        if name == "url":
            continue
        print(f"  {name} ({len(values)}):")
        for value in values:
            print(f"    {value}")


if __name__ == "__main__":
    main()
