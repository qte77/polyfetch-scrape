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
             wait_until / wait_for_* / screenshot)
                         │
      terminal 4xx/451 ──┴── raise_for_terminal_status ──► AuthRequired / GoneError / LegalBlock
```

Every tier runs the same retry loop (`RetryPolicy`, honoring `Retry-After`) and returns the same typed
`Response`, so callers never branch on which tier succeeded — `Response.backend` records it.

## Component responsibilities

| Module | Responsibility |
|---|---|
| `client.py` | Public `fetch()` orchestrator: conditional headers, optional per-host `Throttle` (pre-dispatch spacing), tier-range escalation (`min_tier`/`max_tier`; `tier=` pins one), request-body routing (`json`/`content`, httpx/curl only), `RenderOptions` plumbing to the patchright tier. |
| `throttle.py` | `Throttle` — thread-safe per-host minimum inter-request spacing (proactive politeness); shared across a bulk worker pool. |
| `_backends/__init__.py` | Shared backend helpers: `FingerprintBlock` sentinel, `raise_for_terminal_status` (`_TERMINAL` map), `permanent_redirect_target`. |
| `_backends/httpx_backend.py` | Tier 1: plain `httpx` + browser-default headers; first attempt for every request. |
| `_backends/curl_backend.py` | Tier 2: `curl_cffi` Chrome TLS impersonation; engages on 403 / TLS error. |
| `_backends/patchright_backend.py` | Tier 3: headless Patchright/Chromium; applies `RenderOptions` (wait strategies, screenshot, opt-in console/network-failure capture). |
| `response.py` | Frozen `Response` (url, status, headers, body, content_type, backend, permanent_redirect_to, screenshot, console_errors, network_failures, screenshots). |
| `render_options.py` | `RenderOptions` + `RenderAction` + `Screenshot` — patchright-tier controls (waits, screenshot, scripted actions, named multi-screenshots, capture_console, capture_network_failures). |
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
