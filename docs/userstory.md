# User stories

Who polyfetch-scrape serves and what they need. Expand as new consumers come online.

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

Covered by: the playwright tier + `RenderOptions(wait_until="networkidle", wait_for_function=...,
screenshot=...)` → `Response.screenshot` (#67, #68).

## Caller handling auth / gone / legal-block outcomes

> As a caller, I want terminal HTTP outcomes as typed exceptions I can catch, not `200`-shaped
> `Response` objects I have to inspect.

Covered by: `AuthRequired` (401/407), `GoneError` (404/410), `LegalBlock` (451) (#27/#28/#30).

## Caller controlling cost and escalation depth

> As a caller in CI or a latency-sensitive path, I don't want a fetch silently escalating to a heavy
> headless browser — and sometimes I want to force the JS tier straight away.

Covered by: `fetch(url, min_tier=..., max_tier=...)` and the `--min-tier` / `--max-tier` CLI flags —
cap escalation (`max_tier="curl_cffi"` never launches Chromium) or force a tier (#80).

## Author of a domain adapter (arXiv, USPTO, ...)

> As someone building a paper/patent client, I want the fetch/anti-bot machinery without
> reimplementing it — but I don't want that domain code bloating the core toolkit.

Covered by: `fetch()` as the public seam; adapters live **downstream** (e.g. `gha-rxiv-feed-action`;
USPTO — #89), never in core.
