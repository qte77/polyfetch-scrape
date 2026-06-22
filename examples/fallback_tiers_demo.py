"""Exemplify the three fallback tiers: httpx -> curl_cffi -> Patchright.

Run via ``make demo_tiers`` or ``uv run python examples/fallback_tiers_demo.py``.
Tier 3 needs the browser binary: ``make setup_browsers``.

A ToS-safe target that *forces* ``fetch()`` to escalate and win at tier 2 or 3
does not reliably exist (open sandboxes resolve at tier 1; the hardest anti-bot
challenges 403 every tier — see ``examples/fallback-tier-targets.txt``). So this
drives each backend directly to show what that tier uniquely provides:

- tier 1 ``httpx``     — plain fetch.
- tier 2 ``curl_cffi`` — a *browser* TLS/JA3 fingerprint (vs httpx's Python one).
- tier 3 ``patchright``— JS render + a screenshot (the visual ground truth).
"""

import json
from pathlib import Path

from polyfetch_scrape._backends import curl_backend, httpx_backend
from polyfetch_scrape.retry import RetryPolicy

TLS_ECHO = "https://tls.peet.ws/api/all"
JS_PAGE = "https://www.scrapingcourse.com/javascript-rendering"
SHOTS_DIR = Path(__file__).parent / "screenshots"
POLICY = RetryPolicy(max_attempts=1)


def _ja3_hash(backend: object) -> tuple[int, str, str]:
    resp = backend.attempt("GET", TLS_ECHO, None, 30.0, POLICY)  # type: ignore[attr-defined]
    tls = json.loads(resp.body).get("tls", {})
    return resp.status, resp.backend, str(tls.get("ja3_hash"))


def demo_tiers_1_and_2() -> None:
    print("Tier 1 (httpx) vs Tier 2 (curl_cffi) — TLS JA3 fingerprint")
    h_status, h_backend, h_ja3 = _ja3_hash(httpx_backend)
    c_status, c_backend, c_ja3 = _ja3_hash(curl_backend)
    print(f"  {h_backend:<10} {h_status}  ja3={h_ja3}")
    print(f"  {c_backend:<10} {c_status}  ja3={c_ja3}")
    verdict = "DIFFER — curl_cffi presents a browser fingerprint" if h_ja3 != c_ja3 else "same"
    print(f"  -> fingerprints {verdict}\n")


def demo_tier_3() -> None:
    from patchright.sync_api import sync_playwright

    SHOTS_DIR.mkdir(exist_ok=True)
    shot = SHOTS_DIR / "tier3-scrapingcourse-js.png"
    print("Tier 3 (Patchright/Chromium) — JS render + screenshot")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(JS_PAGE, wait_until="networkidle")
        title = page.title()
        page.screenshot(path=str(shot), full_page=True)
        browser.close()
    repo_root = Path(__file__).parent.parent
    print(f"  rendered {JS_PAGE} (title={title!r})")
    print(f"  screenshot -> {shot.relative_to(repo_root)}")


def main() -> None:
    demo_tiers_1_and_2()
    demo_tier_3()


if __name__ == "__main__":
    main()
