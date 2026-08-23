<!-- markdownlint-disable MD033 -->
# Public API reference

The complete public surface of `polyfetch_scrape`. Everything under `_backends/` is private; only the names below are importable from the package root (`from polyfetch_scrape import fetch, Response, RenderOptions, RenderAction, RetryPolicy, FetchError, ...`).

## `fetch`

```python
fetch(url, *, method="GET", headers=None, timeout=30.0, retry=None,
      browser="chrome", wait_for_selector=None, tier=None,
      min_tier=None, max_tier=None, etag=None, last_modified=None,
      json=None, content=None, throttle=None, render=None) -> Response
      # tier pins one backend: "httpx"|"curl_cffi"|"patchright" (≡ min_tier==max_tier)
      # min_tier / max_tier → bound the fallback range: max_tier="curl_cffi" caps escalation
      #   (never launches the browser); min_tier="patchright" forces the JS tier
      # etag / last_modified → If-None-Match / If-Modified-Since (conditional GET)
      # json=<obj> / content=<bytes> → POST/PUT request body (mutually exclusive)
      # throttle=Throttle(min_interval=…) → proactive per-host spacing (share one across calls)
      # render=RenderOptions(...) → patchright-tier wait/screenshot controls
```

A single call runs the three-tier fallback chain (or the pinned `tier`) and returns a typed `Response` regardless of which backend succeeded.

**Request bodies (`json` / `content`) use the httpx and curl_cffi tiers only.** The patchright tier is GET-only and cannot replay a body, so a body request that would otherwise escalate to patchright — or one pinned to `tier="patchright"` — raises `FetchError` instead of silently dropping the body. Passing both `json` and `content` also raises `FetchError`. POST is not idempotent, but body requests are still retried on the same connection/timeout + `retry_on_status` conditions as any other request.

CLI: `polyfetch fetch <url> [--device NAME] [--viewport WxH] [--color-scheme light|dark|no-preference] [--user-agent STR] [--locale STR] [--video-out DIR]` — the patchright-tier emulation/video flags; `--json` additionally surfaces `screenshot_b64` (PNG) and `video_path` (recording) when requested. Full flag list: [USING.md](../USING.md).

## Throttle (optional per-host rate limit)

```python
Throttle(min_interval: float)   # seconds between same-host requests; <= 0 disables (no-op)
throttle.acquire(url)           # thread-safe; blocks to enforce this host's next slot
```

Proactive politeness: pass one **shared** `Throttle` to many `fetch(url, throttle=t)` calls (or use
`polyfetch bulk --delay SECONDS`, which builds one shared across the worker pool) to keep at least
`min_interval` seconds between requests to the **same host** (keyed by hostname); different hosts never
block each other. It spaces distinct `fetch()` calls — internal retries / tier-escalation within one
call already honor `Retry-After` / backoff. Per-process (not distributed).

## Render controls (patchright tier)

```python
RenderOptions(wait_until="domcontentloaded"|"load"|"networkidle", wait_for_selector=None,
              wait_for_function=None, screenshot=None, actions=(), screenshots=(),
              capture_console=False, capture_network_failures=False, capture_network_log=False,
              viewport=None, device=None, color_scheme=None, user_agent=None, locale=None,
              record_video_dir=None, record_video_size=None)
      # patchright tier only; screenshot="viewport"|"full_page"|"<css-selector>" → Response.screenshot (PNG bytes)
      # actions=(RenderAction(...), ...) run in order BEFORE waits/capture (drive → settle → capture)
      # screenshots=(Screenshot(...), ...) → Response.screenshots (dict[name, PNG bytes]); after waits
      # capture_console → Response.console_errors (console + uncaught-JS errors)
      # capture_network_failures → Response.network_failures (failed requests + HTTP >= 400)
      # capture_network_log → Response.network_log (EVERY completed request, not just failures)
      # --- emulation + video: set at browser new_context() time (both the fetch tier and
      #     render_session apply these the same way) ---
      # device="<preset name>" (e.g. "iPhone 13") → spreads Patchright's device dict
      #     (user_agent/viewport/is_mobile/has_touch/device_scale_factor/default_browser_type/...);
      #     explicit viewport/user_agent/locale/color_scheme below override the preset's values.
      #     NOTE: on an is_mobile device the "full-page" screenshot clips rather than scrolling.
      # viewport=(width, height) — also changeable post-hoc via page.set_viewport_size(...)
      # color_scheme="light"|"dark"|"no-preference" — also changeable post-hoc via
      #     page.emulate_media(color_scheme=...)
      # user_agent=<str> / locale=<str> (BCP 47, e.g. "en-US") — context-time only
      # record_video_dir=<path> (+ optional record_video_size=(width, height)) → records a
      #     VP8 .webm of the session into that directory; Patchright only finalizes the file on
      #     context.close(), so the path lands on Response.video_path once fetch() returns

RenderAction(verb, selector=None, text=None, value=None, ms=None)
      # verb: "click"(selector) | "click_text"(text) | "fill"(selector,value)
      #     | "wait_for_selector"(selector) | "wait_ms"(ms)

Screenshot(name, target="viewport")
      # target: "viewport" | "full_page" | "<css-selector>" (element shot — must match ONE element)
      # full_page → whole scrollable page (is_mobile devices clip to viewport, not scroll)
```

## Render session (interactive, patchright tier)

A managed, **headless** Patchright `Page` for multi-step interactive flows (act → assert → act) — the interactive counterpart to single-shot `fetch(url, render=...)`. Chromium-only; library-only (no CLI). Console + network-failure capture is always on; the full per-request trace (`s.network_log`) is opt-in via `capture_network_log=True`.

```python
with render_session(url, *, wait_until="domcontentloaded", timeout=30.0,
                     capture_network_log=False,
                     device=None, viewport=None, color_scheme=None, user_agent=None,
                     locale=None, record_video_dir=None, record_video_size=None) as s:
    s.click(sel); s.click_text(text); s.fill(sel, value); s.submit()   # drive
    s.wait_for_selector(sel); s.wait_for_function(js); s.wait_ms(ms)   # settle
    s.shot(name)     # viewport PNG bytes → s.screenshots[name] (also returned)
    s.page           # the managed Patchright Page (escape hatch for structural reads)
    s.network_log    # [{url, method, status, duration_ms}] — only when capture_network_log=True
    s.video_path     # Path to the recorded .webm once set (only after the `with` block exits)
# auto on exit: teardown; s.console_errors / s.network_failures collected throughout;
#   on an exception inside the block → an "exception" screenshot is captured first;
#   s.video_path is set once the context closes, when record_video_dir was given.
# a navigation timeout raises FetchError.
```

`device`/`viewport`/`color_scheme`/`user_agent`/`locale`/`record_video_dir`/`record_video_size` mirror the same-named `RenderOptions` fields above — set at `new_context()` time, same emulation/video semantics. `submit()` presses Enter on the focused element. **Caveat:** `s.console_errors` / `s.network_failures` reflect only *this* process's network — same runner-network caveat as `Response` below.

## `Response` and `RetryPolicy`

```python
Response(url, status, headers, body, content_type, backend,
         permanent_redirect_to=None, screenshot=None, video_path=None,
         console_errors=[], network_failures=[], network_log=[], screenshots={})
      # permanent_redirect_to: Location target on a 301/308, so callers can update stored URLs
      # screenshot: PNG bytes when requested on the patchright tier, else None
      # video_path: Path to the recorded VP8 .webm when RenderOptions.record_video_dir was set
      #   (patchright tier), else None
      # screenshots: dict[name, PNG bytes] from RenderOptions.screenshots; {} otherwise
      # console_errors: console + uncaught-JS error strings (opt-in via RenderOptions.capture_console)
      # network_failures: [{url, error}] (failed request) + [{url, status}] (HTTP >= 400)
      #   opt-in via RenderOptions.capture_network_failures
      # network_log: [{url, method, status, duration_ms}] for EVERY completed request, in completion
      #   order; status/duration_ms are None on a failed/untimed request. opt-in via
      #   RenderOptions.capture_network_log; independent of capture_network_failures
      # CAVEAT: console_errors / network_failures / network_log reflect only THIS process's
      #   network — a failure a real user hits (CORS / extension / proxy) can read clean here;
      #   force a known failure to trust it

RetryPolicy(max_attempts=3, backoff_initial=0.2, backoff_factor=2.0,
            retry_on_status=frozenset({429, 500, 502, 503, 504}))
```

## Exceptions

All subclass `FetchError`. Terminal statuses raise on the first attempt in every tier — no retry, no escalation:

```python
FetchError       # base: retries exhausted on every tier
AuthRequired     # 401 / 407
GoneError        # 404 / 410
LegalBlock       # 451 (RFC 7725) — never escalated to the fingerprint tiers
```

## Structured-source discovery (`utils.discovery`)

Semi-public helper (import by module path — `from polyfetch_scrape.utils.discovery import discover`; not re-exported from the package root). Reports the cheaper-than-HTML entrypoints a site advertises, purely at the fetch layer — it returns URLs/types only and never extracts content.

```python
discover(url: str) -> DiscoveredSources
      # DiscoveredSources(url, sitemaps, event_sitemaps, feeds, llms_txt, json_ld_types) — frozen; tuple[str, ...] fields
      # sitemaps/event_sitemaps ← robots.txt `Sitemap:` lines + confirmed common paths (event* → event_sitemaps)
      # feeds ← <link rel="alternate" type="application/rss+xml|atom+xml|text/calendar"> (resolved absolute)
      # llms_txt ← /llms.txt, /llms-full.txt (soft-404-guarded: a 200 HTML shell is not counted)
      # json_ld_types ← <script type="application/ld+json"> @type values (handles lists + @graph nesting)
      # Never raises for an absent source; raises ValueError if url/a probe is a literal internal IP (SSRF guard).
```

CLI: `polyfetch discover <url> [--json]` (the `--json` payload is `asdict(DiscoveredSources)`).

## CLI-only commands

`polyfetch doctor [--fix]` — checks whether the browser-tier (patchright) Chromium binary is installed; exits non-zero when it's missing. `--fix` installs it. No Python equivalent — CLI-only. Handy when borrowing this repo's venv via `uv run --directory` (see [USING.md](../USING.md)), where the Chromium cache can get wiped between runs.

## Logging

The library logs tier escalations on the `polyfetch_scrape` logger (silent by default via a `NullHandler`) — configure logging in your app to observe which tier each request escalated through.
