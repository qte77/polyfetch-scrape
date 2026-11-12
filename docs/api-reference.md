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

CLI: `polyfetch fetch <url> [--device NAME] [--viewport WxH] [--color-scheme light|dark|no-preference] [--user-agent STR] [--locale STR] [--video-out DIR] [--har-out FILE] [--headed] [--storage-state FILE]` — the patchright-tier emulation/video/HAR/launch/session flags (`--headed` launches Chromium headed instead of headless; default headless — clears some anti-bot challenges a headless launch never does, #190; `--storage-state FILE` resumes a session from a saved Playwright storage-state JSON file, #200); `--json` additionally surfaces `screenshot_b64` (PNG), `video_path` and `har_path` (recordings) when requested, and `request_user_agent` (the UA actually sent, when cheaply knowable — on `fetch` and every `bulk` line; #198). `[--json-body VALUE | --data VALUE]` attach a request body (`VALUE` is a literal string, `@path`, or `@-` for stdin) — mutually exclusive, httpx/curl_cffi-tier only. `cookies=`/`extra_http_headers=` are Python-API-only (`render_session`/`RenderOptions`) — no CLI flag shape fits a cookie list or a repeatable header yet. Full flag list: [USING.md](../USING.md).

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
RenderOptions(
    wait_until="domcontentloaded" | "load" | "networkidle",
    wait_for_selector=None,
    wait_for_function=None,
    screenshot=None,
    actions=(),
    screenshots=(),
    capture_console=False,
    capture_network_failures=False,
    viewport=None,
    device=None,
    color_scheme=None,
    user_agent=None,
    locale=None,
    record_video_dir=None,
    record_video_size=None,
    record_har_path=None,
    record_har_mode="minimal",
    record_har_content="omit",
    headless=True,
    storage_state=None,
    cookies=(),
    extra_http_headers=None,
    capture_network=False,
)
# patchright tier only; screenshot="viewport"|"full_page"|"<css-selector>" → Response.screenshot (PNG bytes)
# actions=(RenderAction(...), ...) run in order BEFORE waits/capture (drive → settle → capture)
# screenshots=(Screenshot(...), ...) → Response.screenshots (dict[name, PNG bytes]); after waits
# capture_console → Response.console_errors — browser-generated messages only (e.g. a CORS
#     failure); page-script console.* calls and, very likely, page-script uncaught exceptions
#     are NOT captured (patchright disables the Console API and avoids Runtime.enable — see
#     USING.md § DevTools capture caveat for the verified source and a DOM-attribute alternative)
# capture_network_failures → Response.network_failures (failed requests + HTTP >= 400)
# --- emulation + video: set at browser new_context() time (both the fetch tier and
#     render_session apply these the same way) ---
# device="<preset name>" (e.g. "iPhone 13") → spreads Patchright's device dict
#     (user_agent/viewport/is_mobile/has_touch/device_scale_factor/default_browser_type/...);
#     explicit viewport/user_agent/locale/color_scheme below override the preset's values.
#     NOTE: on an is_mobile device the "full-page" screenshot clips rather than scrolling.
#     device={...} — a CUSTOM bundle for a device the registry does not carry; same
#     override precedence. An unknown preset NAME raises ValueError naming near-misses;
#     list the presets with `polyfetch devices`.
# viewport=(width, height) — also changeable post-hoc via page.set_viewport_size(...)
# color_scheme="light"|"dark"|"no-preference" — also changeable post-hoc via
#     page.emulate_media(color_scheme=...)
# user_agent=<str> / locale=<str> (BCP 47, e.g. "en-US") — context-time only
# record_video_dir=<path> (+ optional record_video_size=(width, height)) → records a
#     VP8 .webm of the session into that directory; Patchright only finalizes the file on
#     context.close(), so the path lands on Response.video_path once fetch() returns
# record_har_path=<path> (+ optional record_har_mode="full"|"minimal",
#     record_har_content="omit"|"embed"|"attach") → records a HAR 1.2 file of every
#     request the session makes, at that exact path; lands on Response.har_path once
#     fetch() returns (same context.close()-finalization timing as the video).
#     Defaults: "minimal" mode, "omit" content (no response bodies).
#     SECURITY: a HAR records every request/response header, including Cookie and
#     Authorization — treat it as a credentials-bearing artifact once an authenticated
#     session is in play, and never commit or share one uninspected.
# headless=True|False — launch Chromium headless (default) or headed. A headed launch is
#     heavier but clears some anti-bot challenges a headless launch never does (#190); on a
#     display-less host (e.g. CI) run it under `xvfb-run -a` to stay unattended.
# --- authenticated sessions (#200): set at new_context() time, both fetch() and
#     render_session apply these the same way ---
# storage_state=<path|dict> → Playwright storage state (cookies + localStorage); the context
#     is authenticated from the FIRST navigation. Capture one with
#     RenderSession.save_storage_state(path) and reuse it non-interactively. A path that
#     doesn't exist, can't be read, or isn't valid JSON raises FetchError naming it, checked
#     before any browser work -- not the raw FileNotFoundError/json.JSONDecodeError Patchright's
#     own loader would otherwise raise, uncaught, deep inside new_context().
#     SECURITY: a storage-state file holds live session credentials — handle it like the
#     HAR/video outputs above, never commit or share one uninspected.
# cookies=({"name":..., "value":..., "url":...}, ...) → cookie dicts added to the context
#     BEFORE the first navigation (Playwright's add_cookies shape) — a targeted alternative
#     to storage_state when all that's on hand is a session token. Composes with
#     storage_state: a different-identity cookie is additive, a same-identity one
#     (name/domain/path) overwrites the storage_state value (add_cookies' own upsert
#     semantics). Sessions are per-origin.
# extra_http_headers={"Authorization": "Bearer ..."} → sent with every request on this
#     context, mirroring fetch(headers=...) for the browser tier. When fetch(headers=...) is
#     ALSO given, the two are merged (fetch(headers=...) wins per key) rather than one
#     silently replacing the other — Patchright's set_extra_http_headers() replaces the whole
#     header set on every call, so this is sent in exactly one call per context. Sent to
#     EVERY origin the page contacts — an Authorization bearer here can leak to third-party
#     CDNs/analytics the page loads.
# capture_network → Response.network_log (#182): a BOUNDED per-request log (url, method,
#     resource_type, status, failure errorText, start_ms + duration_ms), INCLUDING SSE
#     (EventSource) message frames nested under their request's sse_messages (event, data,
#     timestamp_ms) — the gap capture_network_failures doesn't cover (that one stays a cheap
#     failures-only {url,error}/{url,status} subset; keep using it when all you need is "did
#     anything fail"). Uses a SEPARATE CDP session sending only Network.enable — never
#     Runtime.enable/Console.enable/Page.enable, the leaks Patchright's own stealth model
#     specifically patches (its README's "Patches" section); verified not to change
#     page-visible automation signals (navigator.webdriver and friends) and to coexist with
#     HAR recording, page.route, and capture_network_failures. Off by default (zero overhead).
#     BOUNDED: at most 1000 request entries and 1000 SSE messages (cumulative) per session —
#     Response.network_log_truncated / RenderSession.network_log_truncated flips to True once
#     either cap is hit. SSE data is truncated to 2 KB per message (mirrors
#     FingerprintBlock.body_excerpt). NEVER records request/response bodies or header values
#     (nothing header-shaped is read, so there is nothing to redact). Detectability by
#     anti-automation fingerprinting scripts beyond the signals checked above is UNVERIFIED.

RenderAction(verb, selector=None, text=None, value=None, ms=None)
# verb: "click"(selector) | "click_text"(text) | "fill"(selector,value)
#     | "type"(selector,value,ms) | "wait_for_selector"(selector) | "wait_ms"(ms)
# "type" presses keys one at a time (ms = per-key delay). Prefer it over "fill" on
#     framework-controlled inputs (React/Vue/Svelte): fill() sets the DOM value without
#     firing the events onChange listens for, so the submit silently sends stale/empty data.

Screenshot(name, target="viewport")
# target: "viewport" | "full_page" | "<css-selector>" (element shot — must match ONE element)
# full_page → whole scrollable page (is_mobile devices clip to viewport, not scroll)
```

## Render session (interactive, patchright tier)

A managed Patchright `Page` for multi-step interactive flows (act → assert → act) — the interactive counterpart to single-shot `fetch(url, render=...)`. Chromium-only; headless by default (`headless=False` launches headed, #190); library-only (no CLI). Console + network-failure capture is always on — console capture is browser-generated only (see [USING.md § DevTools capture](../USING.md#devtools-capture-console-network-js-errors) caveat); page-script console/exception output needs a DOM-attribute + screenshot signal instead.

```python
with render_session(url, *, wait_until="domcontentloaded", timeout=30.0,
                     device=None, viewport=None, color_scheme=None, user_agent=None,
                     locale=None, record_video_dir=None, record_video_size=None,
                     record_har_path=None, record_har_mode="minimal",
                     record_har_content="omit", headless=True, storage_state=None,
                     cookies=(), extra_http_headers=None, capture_network=False) as s:
    s.click(sel); s.click_text(text); s.fill(sel, value); s.submit()   # drive
    s.wait_for_selector(sel); s.wait_for_function(js); s.wait_ms(ms)   # settle
    s.shot(name)     # viewport PNG bytes → s.screenshots[name] (also returned)
    s.page           # the managed Patchright Page (escape hatch for structural reads)
    s.video_path     # Path to the recorded .webm once set (only after the `with` block exits)
    s.har_path       # Path to the recorded HAR once set (only after the `with` block exits)
    s.network_log    # bounded per-request list (+ nested SSE messages), live, when requested
    s.save_storage_state(path)  # persist cookies+localStorage to path (parent dirs created);
                                 # must be called INSIDE this block — FetchError afterwards
# auto on exit: teardown; s.console_errors / s.network_failures / s.network_log collected
#   throughout; on an exception inside the block → an "exception" screenshot is captured
#   first; s.video_path / s.har_path are set once the context closes, when requested.
# a navigation timeout raises FetchError; so does a storage_state path that doesn't exist,
#   can't be read, or isn't valid JSON — checked before the browser even launches.
```

`device`/`viewport`/`color_scheme`/`user_agent`/`locale`/`record_video_dir`/`record_video_size`/`record_har_path`/`record_har_mode`/`record_har_content`/`headless`/`storage_state`/`cookies`/`extra_http_headers`/`capture_network` mirror the same-named `RenderOptions` fields above — set at launch/`new_context()` time, same emulation/video/HAR/launch/session/capture semantics. `viewport` and `record_video_size` are plain `(width, height)` pixel tuples (e.g. `(1280, 720)`), **not** a `RenderOptions`/dict — passing an `options=` kwarg raises `TypeError`. `submit()` presses Enter on the focused element. **Caveat:** `s.console_errors` / `s.network_failures` / `s.network_log` reflect only *this* process's network — same runner-network caveat as `Response` below. **Security:** a HAR records every request/response header, including `Cookie` and `Authorization` — treat `s.har_path`'s file as a credentials-bearing artifact once an authenticated session is in play. A `storage_state` file (passed in, or written by `save_storage_state`) holds the same kind of live session credentials — handle it identically. `s.network_log` never records bodies or header values, so there is nothing to redact there.

`save_storage_state(path)` persists the session's current cookies + localStorage to `path`, creating the parent directory first (Patchright does **not** create it for a storage-state path the way it does for `screenshot`/`pdf`/`video`). Must be called **inside** the `with` block: the context — and its storage — is gone once it exits, and a call after exit raises `FetchError` instead of a raw driver error against the already-closed context (#200; mirrors the #199 video-path-after-close ordering bug, in reverse).

`timeout` (seconds, default `30.0`) applies to both the `RenderSession` convenience methods above **and** raw calls on `s.page` (`page.set_default_timeout` / `set_default_navigation_timeout` are set right after the page is created) — so e.g. `s.page.locator(sel).click()` honors the same budget instead of Playwright's own 30000ms default.

## `Response` and `RetryPolicy`

```python
Response(
    url,
    status,
    headers,
    body,
    content_type,
    backend,
    permanent_redirect_to=None,
    screenshot=None,
    video_path=None,
    har_path=None,
    request_user_agent=None,
    console_errors=[],
    network_failures=[],
    screenshots={},
    redirect_to=None,
    network_log=[],
    network_log_truncated=False,
)
# permanent_redirect_to: Location target on a 301/308, so callers can update stored URLs
# redirect_to: Location target on ANY unfollowed 3xx (incl. temporary 302/303/307), else None
# screenshot: PNG bytes when requested on the patchright tier, else None
# video_path: Path to the recorded VP8 .webm when RenderOptions.record_video_dir was set
#   (patchright tier), else None
# har_path: Path to the recorded HAR 1.2 file when RenderOptions.record_har_path was set
#   (patchright tier), else None. SECURITY: a HAR records every request/response header,
#   including Cookie/Authorization — treat it as a credentials-bearing artifact once an
#   authenticated session is in play
# request_user_agent: the User-Agent actually sent, when cheaply knowable — httpx/curl_cffi:
#   from the merged outgoing headers (curl_cffi's impersonate= profile picks one natively and
#   isn't readable unless you override it yourself); patchright: the context's user_agent when
#   --user-agent/--device set it. None otherwise (#198; see USING.md for the UA-substitution
#   caveat — a 200 with a substituted UA is not proof a site is open to every client)
# screenshots: dict[name, PNG bytes] from RenderOptions.screenshots; {} otherwise
# console_errors: console + uncaught-JS error strings (opt-in via RenderOptions.capture_console)
# network_failures: [{url, error}] (failed request) + [{url, status}] (HTTP >= 400)
#   opt-in via RenderOptions.capture_network_failures
# CAVEAT: console_errors / network_failures reflect only THIS process's network — a failure a
#   real user hits (CORS / extension / proxy) can read clean here; force a known failure to trust it
# CAVEAT (patchright tier): console_errors is browser-generated only — page-script console.*
#   calls and, very likely, page-script uncaught exceptions are not captured (patchright disables
#   the Console API and avoids Runtime.enable). See USING.md § DevTools capture for the verified
#   source and a DOM-attribute + screenshot alternative.
# network_log: bounded per-request list — url, method, resource_type, status, error
#   (failure errorText, e.g. "net::ERR_CONNECTION_REFUSED"), start_ms, duration_ms, and
#   sse_messages (a list of {event, data, timestamp_ms} for an EventSource request) — opt-in
#   via RenderOptions.capture_network (#182). Via a SEPARATE CDP session sending only
#   Network.enable (never Runtime/Console/Page) — see RenderOptions.capture_network's
#   docstring for the full stealth-safety verification. Capped at 1000 entries and 1000 SSE
#   messages (cumulative) per session; network_log_truncated is True once either cap is hit.
#   Never carries request/response bodies or header values.

RetryPolicy(
    max_attempts=3,
    backoff_initial=0.2,
    backoff_factor=2.0,
    retry_on_status=frozenset({429, 500, 502, 503, 504}),
)
```

## Exceptions

All subclass `FetchError`. Terminal statuses raise on the first attempt in every tier — no retry, no escalation:

```python
FetchError  # base: retries exhausted on every tier, or a final status outside 2xx/3xx (e.g. 400, 999)
AuthRequired  # 401 / 407
GoneError  # 404 / 410
LegalBlock  # 451 (RFC 7725) — never escalated to the fingerprint tiers
```

Every `FetchError` (and subclass, including the internal `FingerprintBlock` — see architecture.md) carries three diagnostic attributes, all `None` when not captured:

```python
exc.status  # int | None — the terminal/final HTTP status, when known
exc.headers  # dict[str, str] | None — the final tier's blocked/exhausted response headers
exc.body_excerpt  # str | None — that response's body, truncated to 2 KB and decoded lossily
```

`headers`/`body_excerpt` are populated only for the **final tier's** raise (the one that actually surfaces to the caller — see architecture.md's escalation loop): the response headers with `Set-Cookie` always redacted (never a request header/cookie), and the body excerpt bounded at 2 KB so a large challenge page never balloons an exception. They let a caller tell a pure TLS/fingerprint block from a session/behavioral one (see #209) without dropping to `render_session` and hand-rolling event listeners. `fetch --json`'s error payload mirrors these as optional `headers`/`body_excerpt` keys (see [USING.md](../USING.md) "Errors & exit codes").

## Structured-source discovery (`utils.discovery`)

Semi-public helper (import by module path — `from polyfetch_scrape.utils.discovery import discover`; not re-exported from the package root). Reports the cheaper-than-HTML entrypoints a site advertises, purely at the fetch layer — it returns URLs/types only and never extracts content.

```python
discover(url: str) -> DiscoveredSources
      # DiscoveredSources(url, sitemaps, event_sitemaps, feeds, llms_txt, json_ld_types) — frozen; tuple[str, ...] fields
      # sitemaps/event_sitemaps ← robots.txt `Sitemap:` lines + confirmed common paths (event* → event_sitemaps)
      # feeds ← <link rel="alternate" type="application/rss+xml|atom+xml|text/calendar"> (resolved absolute)
      # llms_txt ← /llms.txt, /llms-full.txt (soft-404-guarded: a 200 HTML shell is not counted)
      # json_ld_types ← <script type="application/ld+json"> @type values (handles lists + @graph nesting)
      # Never raises for an absent source, and never for url itself — the seed is never
      # blocked (even a literal internal IP or localhost). Raises ValueError if a URL
      # discover() derives from url (a probed path, a redirect target) is internal, and
      # url is external (SSRF guard, escalation-only — see architecture.md's utils/_ssrf.py row).
```

CLI: `polyfetch discover <url> [--json]` (the `--json` payload is `asdict(DiscoveredSources)`).

## Robots.txt compliance helper (`utils.robots`, opt-in)

Semi-public helper (import by module path — `from polyfetch_scrape.utils.robots import is_allowed`; not re-exported from the package root). **Opt-in and dual-use** (#147): neither `fetch()` nor `discover()` calls this automatically — a caller that wants robots.txt enforcement calls it itself. No CLI equivalent.

```python
is_allowed(url: str, user_agent: str = "*") -> bool
      # Fetches + parses url's origin's /robots.txt (reuses utils.discovery's
      # fetch_robots_txt_status(), the same escalation-only SSRF guard as discover()) and
      # reports allow/deny via the stdlib urllib.robotparser (RFC 9309) for a successful
      # fetch — no hand-rolled parsing. Two RFC 9309 rules are checked explicitly rather
      # than left to whichever urllib.robotparser version is installed (verified: the
      # "/robots.txt is implicitly allowed" special case exists in Python 3.14's stdlib,
      # not in 3.12's):
      #   - §2.2.2: "The /robots.txt URI is implicitly allowed" — url being /robots.txt
      #     itself short-circuits to True before any fetch.
      #   - §2.3.1.3 "Unavailable" (HTTP 4xx incl. 404, or an HTML soft-404 shell) →
      #     allow everything. §2.3.1.4 "Unreachable" (HTTP 5xx, or a network/transport
      #     failure with no HTTP response at all) → disallow everything.
      # url is the seed — never blocked (even a literal internal IP or localhost).
      # Raises ValueError if the derived /robots.txt fetch resolves to, or
      # redirects to, an internal address while url is external (SSRF guard,
      # escalation-only — see architecture.md's utils/_ssrf.py row).
```

## CLI-only commands

`polyfetch doctor [--fix] [--headed]` — checks whether the browser-tier (patchright) Chromium binary is installed; exits non-zero when it's missing. `--fix` installs it. `--headed` probes a headed launch instead of headless — useful to verify a display (e.g. `xvfb-run -a`) actually works, not just that the binary is installed (#190). No Python equivalent — CLI-only. Handy when borrowing this repo's venv via `uv run --directory` (see [USING.md](../USING.md)), where the Chromium cache can get wiped between runs. **On musl (Alpine)** — patchright publishes no `musllinux` wheel, so the browser tier cannot run there at all; `doctor` detects this and exits non-zero with a message naming the workaround (`--max-tier curl_cffi` / `max_tier="curl_cffi"`) before probing or trying to install anything (#197). The httpx and curl_cffi tiers are unaffected.

`polyfetch devices` — lists the Patchright device preset names usable with `fetch --device` (or `RenderOptions(device=...)`), one per line. Starts the Patchright driver but launches no browser. No public Python equivalent — the enumeration lives in the private backend. For a device the registry doesn't carry, pass a custom bundle instead: `fetch --device-json '{...}'` / `RenderOptions(device={...})`.

## Logging

The library logs tier escalations on the `polyfetch_scrape` logger (silent by default via a `NullHandler`) — configure logging in your app to observe which tier each request escalated through.
