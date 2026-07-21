# Architecture

How a single `fetch(url)` call flows through the three-tier fallback chain to a typed `Response`.

## Data flow

```text
                    fetch(url, ...)                    src/polyfetch_scrape/client.py
                         │
              _with_conditional_headers    (etag / last_modified → If-None-Match / If-Modified-Since)
                         │
   _resolve_tier_range(tier / min_tier / max_tier) → active slice of the chain below
                         │   default: full chain · tier= pins one · min_tier skips cheaper · max_tier caps
                         ▼   (_run_chain walks the slice; _dispatch calls each tier)
               httpx_backend.attempt ──2xx──► Response
                         │
                FingerprintBlock (403 / TLS error)
                         ▼
               curl_backend.attempt  ──2xx──► Response
                (chrome TLS impersonation)
                         │
                FingerprintBlock
                         ▼
            patchright_backend.attempt ──2xx──► Response
            (headless Chromium; RenderOptions:
             wait_until / wait_for_* / screenshot
             + emulation/video)
                         │
      terminal 4xx/451 ──┴── raise_for_terminal_status ──► AuthRequired / GoneError / LegalBlock
```

Every tier runs the same retry loop (`RetryPolicy`, honoring `Retry-After`) and returns the same typed
`Response`, so callers never branch on which tier succeeded — `Response.backend` records it.

## Two layers: engine and scripts

polyfetch has a supported **engine** and an unsupported-surface **scripting substrate**:

- **Engine (stable, semver'd):** `fetch`, `render_session`, `discover`, and the value objects `Response`, `RenderOptions`, `RenderAction`, `Screenshot`, `RetryPolicy`, `Throttle`, plus the `FetchError` hierarchy. This is the public API.
- **Scripts:** the live `render_session().page` (stealth-Patchright `Page`) for app-specific flows. `_backends/` is private; `contrib/` is unsupported and never imported by core.

**The ownership line (decidable):** polyfetch owns X iff X is **(a) generic** — true for any target site, not tied to one app's DOM/flow — **and (b) construction-time or shared plumbing** — set at browser/`new_context()` time, or boilerplate every consumer re-implements identically (install, teardown, capture, SSRF). Otherwise the consumer owns it (app-specific, or a few lines on `.page`). Applied: device/locale/video/user-agent emulation → engine (`new_context()`-time); `aria_snapshot` and multi-step walks → scripted `.page` recipes.

For how the estate consumes this substrate across repos — and the promotion rule for when a consumer's need becomes core — see [`docs/estate.md`](estate.md).

## Component responsibilities

| Module | Responsibility |
|---|---|
| `client.py` | Public `fetch()` orchestrator: conditional headers, optional per-host `Throttle` (pre-dispatch spacing), tier-range escalation (`min_tier`/`max_tier`; `tier=` pins one), request-body routing (`json`/`content`, httpx/curl only), `RenderOptions` plumbing to the patchright tier. |
| `throttle.py` | `Throttle` — thread-safe per-host minimum inter-request spacing (proactive politeness); shared across a bulk worker pool. |
| `_backends/__init__.py` | Shared backend helpers: `FingerprintBlock` sentinel, `raise_for_terminal_status` (`_TERMINAL` map), `permanent_redirect_target`. |
| `_backends/httpx_backend.py` | Tier 1: plain `httpx` + browser-default headers; first attempt for every request. |
| `_backends/curl_backend.py` | Tier 2: `curl_cffi` (Python **CFFI** bindings to the **curl-impersonate** fork of curl) — replays a real browser's Chrome TLS/JA3 handshake, which UA/header edits alone can't; engages on 403 / TLS error. |
| `_backends/patchright_backend.py` | Tier 3: headless Patchright/Chromium — Patchright is a stealth, API-compatible **Playwright fork** (the dependency is `patchright`, never `playwright`); applies `RenderOptions` (wait strategies, screenshot, opt-in console/network-failure capture); emulation/video applied at `new_context()`. |
| `response.py` | Frozen `Response` (url, status, headers, body, content_type, backend, permanent_redirect_to, screenshot, video_path, console_errors, network_failures, screenshots). |
| `render_options.py` | `RenderOptions` + `RenderAction` + `Screenshot` — patchright-tier controls (waits, screenshot, scripted actions, named multi-screenshots, capture_console, capture_network_failures, device/viewport/color_scheme/user_agent/locale emulation, record_video_dir/record_video_size). |
| `render_session.py` | `render_session()` — managed headless multi-step Patchright `Page` context manager for interactive act→assert→act flows; reuses the backend's `attach_capture`/`capture_screenshot`. |
| `utils/sitemap.py` | `fetch_sitemap_urls()` — sitemap.xml URL discovery (index recursion, gzip, `defusedxml`, literal-IP SSRF guard) over the public `fetch()`. |
| `utils/discovery.py` | `discover()` — structured-entrypoint discovery (sitemaps/feeds/`llms.txt`/JSON-LD `@type`) over `fetch()`; soft-404-guarded; returns URLs/types only (no extraction). Shares the SSRF guard via `utils/_ssrf.py`. |
| `retry.py` | `RetryPolicy` + `should_retry` + `Retry-After` parsing and capped backoff. |
| `errors.py` | Exception taxonomy: `FetchError` base + terminal `AuthRequired` / `GoneError` / `LegalBlock`. |
| `cli.py` | Thin typer CLI over `fetch` / bulk; opt-in `contrib` subcommands. |

## Invariants

- **Every tier returns the same typed `Response`.** Callers don't branch on backend; `Response.backend`
  records which tier served the request.
- **Terminal statuses raise in every tier** (401/407 → `AuthRequired`, 404/410 → `GoneError`, 451 →
  `LegalBlock`) — no retry, no escalation; 451 never reaches the fingerprint tiers (RFC 7725).
- **Escalation is fingerprint-only.** Only `FingerprintBlock` (403 / TLS error) escalates along the
  active tier range (default httpx → curl_cffi → patchright; bounded by `min_tier`/`max_tier`); every
  other outcome returns or raises immediately.
- **Browser-tier controls stay on the browser tier.** `RenderOptions` (wait strategies, screenshots) is
  a no-op on the httpx / curl_cffi tiers; screenshots require the patchright tier.
- **Core is horizontal.** Domain API wrappers and content extraction live in downstream packages that
  consume `fetch()`; `contrib/` extras are unsupported and never imported by core.
- **No unconditional network at import.** Fetching happens only inside `fetch()` / a backend `attempt()`.
- **Value objects are frozen dataclasses, not validation models.** `Response` / `RenderOptions` / `RetryPolicy` / `Throttle` are `@dataclass(frozen=True, slots=True)` — *outputs and config*, not an input-validation boundary. polyfetch therefore uses **no `pydantic` / `pydantic-settings`** and **no env/global settings** (it's a library, not an app; configuration is explicit function parameters). Untrusted input is validated where it enters: `defusedxml` / `json` parsing and the shared `utils/_ssrf.py` literal-IP guard. Whether the estate standardises on pydantic downstream is tracked separately as an open cross-repo question ([#164](https://github.com/qte77/polyfetch-scrape/issues/164)).
- **polyfetch owns the substrate, not app-specific e2e.** The engine + the `new_context()`-time knobs + shared plumbing (install/teardown/capture/SSRF) are core; per-app walks, selectors, and assertions belong to the consumer (see the ownership line above).
