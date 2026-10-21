# Scripting cookbook

Worked recipes for the **scripting substrate** — the second of polyfetch's [two
layers](../README.md#two-layers-engine--scripting-substrate). `render_session(url)`
owns the browser install, launch/teardown, console/network capture, and the SSRF
guard; you own the app-specific steps once you have a live `Page` on `s.page`. Every
snippet below uses only the public `RenderSession` surface: `click` / `click_text` /
`fill` / `submit` / `wait_for_selector` / `wait_for_function` / `wait_ms` / `shot`,
plus `.page`, `s.console_errors`, `s.network_failures`, `s.screenshots`, `s.video_path`,
and `s.har_path`.

## DevTools capture

Wire any `page.on(...)` listener to react to DevTools events as the page runs — the
same signals the Chrome DevTools console/network panels show:

```python
from polyfetch_scrape import render_session

with render_session(url) as s:
    s.page.on("console", lambda m: print(m.type, m.text))  # console.log/warn/error
    s.page.on("pageerror", lambda e: print("uncaught JS:", e))  # uncaught JS exceptions
    s.page.on("requestfailed", lambda r: print(r.url, r.failure))  # failed network requests
    s.click_text("Load more")

    print(s.console_errors)  # always-on: console + uncaught-JS errors, whole session
    print(s.network_failures)  # always-on: failed / >=400 requests, whole session
```

You don't have to wire listeners at all — `s.console_errors` and `s.network_failures`
fill for the whole session (initial page load included) with no setup.

> **Caveat:** a headless capture reflects only *this* runner's network. A cross-origin
> failure a real user hits (CORS, a browser extension, a proxy) can succeed here and
> read clean — treat an empty capture as "no error on this network", not "no error".

## HAR summary recipe

`record_har_path` (on `render_session(...)` or `RenderOptions`) writes a standard HAR 1.2 file
of every request the session makes — openable in Chrome DevTools or any HAR viewer. This is a
**recipe, not an engine helper** (AHA): summarizing a HAR is app-specific (which breakdown you
care about varies), so it stays a snippet here rather than a `utils.har` module or `polyfetch har`
command, until a second consumer needs the same summary.

```python
import json
from collections import Counter
from urllib.parse import urlparse

from polyfetch_scrape import render_session


def _resource_type(mime_type: str) -> str:
    if "html" in mime_type:
        return "document"
    if "javascript" in mime_type:
        return "script"
    if "css" in mime_type:
        return "stylesheet"
    if mime_type.startswith("image/"):
        return "image"
    if "json" in mime_type:
        return "xhr/fetch"
    return "other"


def summarize_har(path: str) -> None:
    with open(path) as f:
        entries = json.load(f)["log"]["entries"]

    document_host = urlparse(entries[0]["request"]["url"]).netloc if entries else None
    by_host = Counter(urlparse(e["request"]["url"]).netloc for e in entries)
    by_type = Counter(_resource_type(e["response"]["content"].get("mimeType", "")) for e in entries)
    failures = [
        e for e in entries if e["response"]["status"] == 0 or e["response"]["status"] >= 400
    ]
    total_bytes = sum(max(e["response"]["content"].get("size", 0), 0) for e in entries)
    slowest = sorted(entries, key=lambda e: e.get("time", 0), reverse=True)[:5]
    third_party = sorted(h for h in by_host if h and h != document_host)

    print("Requests by host:", dict(by_host))
    print("Requests by type:", dict(by_type))
    print(f"Failures ({len(failures)}):", [e["request"]["url"] for e in failures])
    print(f"Total bytes: {total_bytes}")
    print("Slowest requests:")
    for e in slowest:
        print(f"  {e.get('time', 0):.0f}ms  {e['request']['url']}")
    print("Third-party hosts:", third_party)


with render_session(url, record_har_path="session.har") as s:
    s.wait_for_selector(".content")

summarize_har(s.har_path)
```

`response.content.mimeType` and `entry.time` are standard HAR 1.2 fields (not Patchright-specific),
so this works on a HAR from any tool. `stdlib json` only — no new dependency.

> **Security:** a HAR records every request/response header, including `Cookie` and
> `Authorization`. It's safe while polyfetch has no authenticated-session support, but once one
> lands (#200/#178) a HAR taken during a logged-in session **will** contain live credentials.
> Never commit or share a HAR file uninspected — treat it like a secret. `record_har_content`
> defaults to `"omit"` (no response bodies); headers are not redacted.

## Performance trace recipe

`browser.start_tracing()` / `browser.stop_tracing()` capture a raw Chromium trace —
openable in Chrome DevTools' Performance panel — including navigation timing and
paint markers (`firstPaint`, `firstContentfulPaint`, `largestContentfulPaint::Candidate`,
`LayoutShift`). This is a **recipe, not an engine feature** (AHA/#230): it's a low-level,
browser-wide capability, not a per-request concern, so it stays a snippet here rather than
a `capture_performance` option. Core Web Vitals scoring/pass-fail stays a consumer concern
(the estate `perf-cwv-pass` skill), per [`docs/architecture.md`](architecture.md).

Trace the **initial page load** before `render_session()` navigates, so start tracing
first and drive the navigation yourself with raw Patchright — this is the pattern
documented by Patchright itself, and the only one verified to reliably include
navigation + paint markers:

```python
import json

from patchright.sync_api import sync_playwright

TRACE_CATEGORIES = ["loading", "blink.user_timing"]  # minimal set for nav/paint/LCP marks

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    browser.start_tracing(page=page, categories=TRACE_CATEGORIES)
    page.goto("https://example.com", wait_until="load")
    page.wait_for_timeout(300)  # let the trace buffer flush before stopping
    trace_bytes = browser.stop_tracing()
    browser.close()

trace = json.loads(trace_bytes)
events = trace["traceEvents"]
nav_start = next(e for e in events if e["name"] == "navigationStart")
fcp = next(e for e in events if e["name"] == "firstContentfulPaint")
lcp = next((e for e in events if e["name"] == "largestContentfulPaint::Candidate"), None)

print("FCP (ms):", (fcp["ts"] - nav_start["ts"]) / 1000)
if lcp:
    print("LCP (ms):", (lcp["ts"] - nav_start["ts"]) / 1000)
```

To trace a specific **interaction** inside an already-open `render_session()` — e.g. "did
this click cause a layout shift" — reach the browser via `s.page.context.browser` and
start tracing around just that action. This is a **forward** capture (new events during the
window) and was reliable in testing; retroactively re-capturing marks from *before* tracing
started was not (see caveats below), so don't rely on it for the initial-load metrics:

```python
from polyfetch_scrape import render_session

with render_session(url) as s:
    browser = s.page.context.browser
    browser.start_tracing(page=s.page, categories=["loading", "blink.user_timing"])
    s.click_text("Load more")
    s.wait_ms(300)
    trace_bytes = browser.stop_tracing()

trace = json.loads(trace_bytes)
shifts = [e for e in trace["traceEvents"] if e["name"] == "LayoutShift"]
```

A `LayoutShift` event's `args.data.score` is its individual shift score; `had_recent_input`
is `True` for shifts the browser attributes to a recent user action (clicks, typing) — those
are correctly excluded from a cumulative CLS score, matching the CLS spec.

`stdlib json` only, no new dependency. The trace is a plain JSON object (`{"metadata": …,
"traceEvents": [...]}` — Chrome's "Trace Event Format"); `ts` is microseconds on an
internal monotonic clock, so always compute deltas against another event in the same
trace (e.g. `navigationStart`), never against wall-clock time.

**Verified (patchright 1.63.0 / Chromium 153.0.8010.12, 2026-10-21, against
`https://example.com` and a local `python -m http.server` page):**

- `browser.start_tracing()` / `stop_tracing()` work and return a non-empty trace. The
  default category set is large and unfocused (≈800 KB / 3,200+ events for a single trivial
  page load, no paint/LCP markers included); `categories=["loading", "blink.user_timing"]`
  is both smaller (≈100 KB / ~250 events) and the set that actually includes
  `firstContentfulPaint` / `largestContentfulPaint::Candidate` / `navigationStart`.
- `performance.getEntriesByType("navigation")` **is** reachable via `page.evaluate()` and
  returns the full Navigation Timing entry (`domContentLoadedEventEnd`, `loadEventEnd`,
  `transferSize`, etc.) — Patchright's isolated-evaluate-world caveat
  ([`AGENT_LEARNINGS.md`](../AGENT_LEARNINGS.md)) applies to page-script-defined globals, not
  to this native DOM API.
- `performance.getEntriesByType("paint" | "largest-contentful-paint" | "layout-shift")` via
  `page.evaluate()` — including a buffered `PerformanceObserver`, the standard fallback for
  entries that fire before a listener attaches — consistently returned **empty**, even though
  `PerformanceObserver.supportedEntryTypes` lists all three as supported. The *same* paint/LCP
  events are present in the Chrome trace for the same page load. Root cause (a headless-mode
  gap vs. a Patchright-specific restriction) is **UNVERIFIED**; the actionable takeaway is: use
  the trace for paint/LCP/CLS, use `evaluate()` only for Navigation Timing.
- Starting a trace on a page that already finished loading minutes/seconds earlier did
  **not** reliably reproduce that load's `navigationStart`/paint marks — results varied
  run to run. Starting the trace before `page.goto()` (as shown above) was fully reliable
  across repeated runs.
- CDP (`page.context.new_cdp_session(page)`, `Performance.enable` + `Performance.getMetrics`)
  worked without error or any observable anomaly against these benign targets. Whether
  opening a CDP session changes any automation-detection signal was **not** tested — that
  needs a dedicated fingerprinting test page, out of scope for this spike's benign-targets-only
  constraint, and stays **UNVERIFIED**.

## Accessibility snapshot

```python
with render_session(url) as s:
    snap = s.page.locator("body").aria_snapshot()
```

`aria_snapshot()` is the current Patchright API for reading the accessibility tree;
`page.accessibility.snapshot()` was removed upstream, so don't reach for it.

## Multi-step walk

A realistic act → assert → act flow — drive the page, wait for the result to settle,
then act again:

```python
with render_session(url) as s:
    s.click_text("Live")
    s.wait_for_selector("input:not([disabled])")
    s.fill("input", "hello")
    s.submit()
    s.wait_for_selector(".message:last-child")
    s.shot("after")
```

On an exception inside the `with` block, `render_session` captures an `"exception"`
screenshot into `s.screenshots` before teardown — useful for post-mortem debugging a
failed walk without adding your own try/except.

## Framework-controlled inputs — type, don't fill

`s.fill()` (and the `fill` action verb) sets the DOM value directly. On a **controlled
component** — React/Vue/Svelte inputs whose value is bound to framework state — that
leaves the framework's internal state stale, because the `keydown`/`input` events its
`onChange` listens for never fire. The field *looks* filled and the submit sends the
old or empty value:

```python
with render_session(url) as s:
    s.fill("#email", user)  # DOM value set…
    s.fill("#password", pw)  # …framework state never updated
    s.submit()  # server receives EMPTY credentials
```

Type character-by-character instead, which fires the real key events:

```python
with render_session(url) as s:
    s.page.locator("#email").press_sequentially(user, delay=25)
    s.page.locator("#password").press_sequentially(pw, delay=25)
    s.submit()
```

Keep `s.fill()` for plain/uncontrolled forms — it is faster and perfectly correct there.
Like the `evaluate` gotcha below, this one fails *silently*: nothing raises, you just get
the wrong data submitted.

## Live emulation on `.page`

`s.page` exposes Patchright's live emulation calls for changes mid-session:

```python
with render_session(url) as s:
    s.page.set_viewport_size({"width": 1280, "height": 720})
    s.page.emulate_media(color_scheme="dark")
```

These are the *post-hoc* hatches. `device` / `locale` / `user_agent` / video are
context-time only — set once as `render_session(...)` (or `RenderOptions`) arguments,
because they apply at browser `new_context()` time and can't be changed after the page
exists. `viewport` and `color_scheme` sit on the seam: pass them once at
`render_session(...)` time, or change them live on `.page` as above — see
[Two layers](../README.md#two-layers-engine--scripting-substrate) for the full split.

## What NOT to do

`page.evaluate` runs in an **isolated execution world** under Patchright (a stealth
Playwright fork), not the page's main world. The DOM is shared, but a JS global the
page's own scripts define (`window.Foo`) reads back as `undefined` from `evaluate`
even though it exists and works in the page:

```python
with render_session(url) as s:
    s.page.evaluate("() => typeof window.Foo")  # "undefined" — even if Foo is defined and used
```

Don't assert page-script globals via `evaluate`. Use `s.shot(name)` (screenshots) as
ground truth for "did it render", `page.on(...)` for "did it load", and reserve
`evaluate` for DOM you set or read structurally — element presence, attributes,
`textContent`.
