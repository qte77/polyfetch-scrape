---
title: Web Scraping and Data Extraction — Tool Landscape
description: Pointer to the scraping/extraction catalog SSOT in ai-agents-research; retains only polyfetch-scrape's own fallback-chain probe findings
created: 2026-04-23
updated: 2026-06-26
urls_validated: 2026-06-26
---

The scraping / crawling / extraction **tool catalog** (HTTP clients, browser automation, frameworks, AI scrapers, search APIs, managed platforms, document extraction, anti-bot bypass, decision flowchart) is maintained as a single source of truth in `ai-agents-research`:

→ **[Web Scraping & Data Extraction — Tool Landscape (SSOT)](https://github.com/qte77/ai-agents-research/blob/main/docs/non-cc/web-scraping-extraction-landscape.md)** — catalog moved here 2026-06-16 ([ai-agents-research#248](https://github.com/qte77/ai-agents-research/pull/248)).

This repo retains only its own implementation-specific probe data below.

## Status-code taxonomy

How `fetch()` maps HTTP status codes to behaviour and exception types (RFC 9110 / RFC 7725 semantics). Terminal statuses raise on the first attempt in every backend — no retry, no tier escalation — so callers get the same typed error regardless of which tier served the request.

| Status | Meaning | polyfetch-scrape behaviour | Type |
|---|---|---|---|
| 200 | OK | returned | `Response` |
| 301 / 308 | Permanent redirect | followed by the HTTP client; surfacing the final URL on `Response` is planned | — (see [#31](https://github.com/qte77/polyfetch-scrape/issues/31)) |
| 304 | Not Modified | returned unchanged (conditional GET via `etag` / `last_modified`) | `Response(status=304)` |
| 401 / 407 | Unauthorized / Proxy Auth Required | terminal — raises, not retried/escalated | `AuthRequired` |
| 403 | Forbidden | fingerprint signal — escalates to the next tier | `FingerprintBlock` (internal) |
| 404 / 410 | Not Found / Gone | terminal — raises, not retried/escalated | `GoneError` |
| 429 / 5xx | Rate-limit / server errors | retried (honouring `Retry-After`), then raises after exhaustion | `FetchError` |
| 451 | Unavailable For Legal Reasons | terminal — raises, never escalated to fingerprint tiers | `LegalBlock` |

## Empirical findings — polyfetch-scrape probes (2026-04)

Probed in-tree while building the 0.2.0 / 0.3.0 fallback chain. Results are point-in-time and decay — re-run before relying on them.

| Target | plain `httpx` | `curl_cffi` `impersonate="chrome"` | Patchright `chromium.launch(headless=True)` |
|---|---|---|---|
| `httpbin.org/get` | 200 | n/a | n/a |
| `arxiv.org/abs/...` | 200 | n/a | n/a |
| `nowsecure.nl/` | 403 | **200** | 200 |
| `tls.peet.ws/api/all` | TLS verify error | TLS verify error | n/a |
| `g2.com/` | 403 | 403 | **403** |

**Takeaways (with first-party citations):**

- `curl_cffi` `impersonate="chrome"` (no version suffix) is the documented forward-compatible alias — README: *"To keep using the latest browser version as `curl_cffi` updates, simply set `impersonate=\"chrome\"` without specifying a version"* ([curl_cffi README](https://github.com/lexiforest/curl_cffi#requests-like)). Per-version aliases (`chrome131`, `chrome142`, ...) pin a specific TLS/JA3 fingerprint and may be *easier* to fingerprint as bot traffic on targets that track unusual version distributions.
- Patchright's main detection patches are **CDP-layer**: `Runtime.enable` leak (the biggest), `Console.enable` leak, and command-flag leaks like `--enable-automation` and the `navigator.webdriver` flag ([Patchright README → Patches](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#patches)). Chromium-only by design ([README](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#usage)).
- **Caveat on the g2.com result**: my probe used the default `chromium.launch(headless=True)` config. Patchright's README claims it passes Cloudflare ✅ ([README → Stealth](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#stealth)) **but only with the recommended setup**: `launch_persistent_context(channel="chrome", headless=False, no_viewport=True)` and real Chrome rather than Chromium ([README → Best Practice](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#best-practice---use-chrome-without-fingerprint-injection)). Headless + Chromium leaves residual fingerprints (window dimensions, GPU strings, headless-shell binary) that Cloudflare Enterprise can still read. So the g2.com failure is **a config-tier limitation, not a Patchright capability ceiling** — but the recommended config (headed, real Chrome) is incompatible with most CI/server environments, which is the actually-load-bearing constraint.
- Patchright tracks upstream Playwright closely: at probe time, upstream Playwright is `v1.59.1` ([microsoft/playwright releases](https://github.com/microsoft/playwright/releases)) and Patchright is `v1.58.2` ([Patchright PyPI](https://pypi.org/project/patchright/)) — typically <1 minor version of lag. Patchright README notes: *"bugs due to Playwright codebase changes may occur. Fixes for these bugs might take a few days to be released"* ([README → Development](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#development)).
- "Stars aren't a quality signal" applies here — Patchright's small star count (~1.8k vs Playwright's 78k+) reflects niche audience, not maturity. Better signals: upstream-tracking releases, listed in active anti-detect comparisons (this doc), and the explicit list of bot-detection products it claims to pass ([README → Stealth](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#stealth): Brotector, Cloudflare, Kasada, Akamai, Shape/F5, Datadome, Fingerprint.com, CreepJS, Sannysoft, Incolumitas, IPHey, Browserscan, Pixelscan).
