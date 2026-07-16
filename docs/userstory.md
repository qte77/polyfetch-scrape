# User stories

Who polyfetch-scrape serves and what they need. Expand as new consumers come online.

Two personas run through the stories below: **engine users**, who call `fetch`/`discover` and consume
the typed `Response` directly (most stories here), and **script authors**, who drive
`render_session().page` for app-specific interactive flows the engine doesn't express as a knob (see
README's [Two layers](../README.md#two-layers-engine--scripting-substrate)).

## Agent-tooling author hitting the WebFetch ceiling

> As an agent/tool author whose built-in fetch (e.g. Claude Code's WebFetch) got a `403` because it
> can't set headers or impersonate a browser, I want a drop-in `fetch(url)` that escalates through
> browser-shaped headers → TLS impersonation → headless Chromium until something works.

Covered by: the three-tier fallback chain (`httpx` → `curl_cffi` → Patchright); README "When to reach
for this".

## Polling caller re-checking a board on a schedule

> As a periodic job, I don't want to re-download unchanged pages on every run.

Covered by: conditional requests — `fetch(url, etag=..., last_modified=...)` → `304` on `Response`
(#48).

## Caller storing canonical URLs long-term

> As a source-of-truth list, I want to know when a URL moved *permanently* so I can update my stored
> address — and ignore temporary redirects.

Covered by: `Response.permanent_redirect_to` on 301/308 (#31).

## Caller scraping a JS-rendered page

> As someone scraping a client-rendered app, I want the hydrated DOM (and optionally a screenshot)
> without hand-writing a Patchright script.

Covered by: the patchright tier + `RenderOptions(wait_until="networkidle", wait_for_function=...,
screenshot=...)` → `Response.screenshot` (#67, #68), plus opt-in
`RenderOptions(capture_console=True, capture_network_failures=True)` → `Response.console_errors` /
`Response.network_failures` to assert the page hydrated without console/network errors (#118). For a
genuine **interactive** flow (act → assert → act — click, fill a composer, submit, re-assert), use
`render_session(url)` for a managed multi-step `Page` instead of a single `fetch()` (#117).

## Caller handling auth / gone / legal-block outcomes

> As a caller, I want terminal HTTP outcomes as typed exceptions I can catch, not `200`-shaped
> `Response` objects I have to inspect.

Covered by: `AuthRequired` (401/407), `GoneError` (404/410), `LegalBlock` (451) (#27/#28/#30).

## Caller controlling cost and escalation depth

> As a caller in CI or a latency-sensitive path, I don't want a fetch silently escalating to a heavy
> headless browser — and sometimes I want to force the JS tier straight away.

Covered by: `fetch(url, min_tier=..., max_tier=...)` and the `--min-tier` / `--max-tier` CLI flags —
cap escalation (`max_tier="curl_cffi"` never launches Chromium) or force a tier (#80).

## Polite bulk caller respecting published limits

> As someone fetching many URLs from a few hosts, I want to stay under documented rate limits
> proactively — not just react to 429s after I've already tripped them.

Covered by: a shared `Throttle(min_interval=...)` via `fetch(url, throttle=...)`, and
`polyfetch bulk --delay SECONDS` (one throttle across the worker pool → per-host spacing under
concurrency) (#49).

## Caller who'd rather parse structured data than scrape HTML

> As someone building a scraper, before I LLM-scrape a page's HTML I want to know whether the site
> already exposes a cheaper structured entrypoint (a sitemap, an RSS/Atom feed, `llms.txt`, or
> JSON-LD) so I can parse that instead.

Covered by: `utils.discovery.discover(url)` and `polyfetch discover` — reports sitemaps / event
sitemaps / feeds / `llms.txt` / JSON-LD `@type`s (soft-404-guarded), staying at the transport layer
(entrypoint URLs/types only; extraction stays downstream) (#135).

## Author of a domain adapter (arXiv, USPTO, ...)

> As someone building a paper/patent client, I want the fetch/anti-bot machinery without
> reimplementing it — but I don't want that domain code bloating the core toolkit.

Covered by: `fetch()` as the public seam; adapters live **downstream** (e.g. `gha-rxiv-feed-action`;
USPTO — #89), never in core.
