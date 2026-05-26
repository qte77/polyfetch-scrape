# Roadmap

## 0.1.0 — HTTP Client

`httpx`-based HTTP client with retry logic and typed responses.

**Goals**:

- Async and sync `httpx` client wrapper
- Configurable retry with backoff
- Typed response model (status, headers, body, content-type)

## 0.2.0 — TLS Fallback

`curl_cffi` TLS-fingerprint fallback for sites that block standard TLS stacks.

**Goals**:

- Drop-in fallback when `httpx` receives 403/429 or TLS error
- Browser TLS profile selection (chrome, firefox)
- Unified response type shared with 0.1.0 client

## 0.3.0 — JS-Render Fallback

Playwright fallback for pages requiring JavaScript execution.

**Goals**:

- Triggered automatically when curl_cffi fallback also fails
- Wait-for-selector + full-page HTML extraction
- Shared response type; caller receives same structure regardless of backend

## 0.3.x — Status-Code Taxonomy & Header Hygiene

Patch-stage refinements to the existing three-tier fallback so that
non-fingerprint failure modes (auth, gone, rate-limit, legal block) are
handled per RFC 9110 semantics instead of being retried/escalated blindly.

**Goals** (each tracked as its own issue):

- Send `Accept` and `Accept-Language` defaults from the httpx tier — [#26](https://github.com/qte77/polyfetch-scrape/issues/26)
  ([RFC 9110 §12.5.1](https://datatracker.ietf.org/doc/html/rfc9110#section-12.5.1),
  [§12.5.4](https://datatracker.ietf.org/doc/html/rfc9110#section-12.5.4))
- Split exception types: add `AuthRequired` (401/407) and `GoneError` (404/410)
  alongside `FingerprintBlock` and `FetchError` — [#27](https://github.com/qte77/polyfetch-scrape/issues/27)
- Don't retry terminal 4xx (401/404/410/451) inside `_attempt_once` — [#28](https://github.com/qte77/polyfetch-scrape/issues/28)
- Respect `Retry-After` header on 429/503 before falling back to exponential backoff — [#29](https://github.com/qte77/polyfetch-scrape/issues/29)
  ([RFC 9110 §10.2.3](https://datatracker.ietf.org/doc/html/rfc9110#section-10.2.3))
- Treat 451 distinctly — don't escalate to fingerprint tiers — [#30](https://github.com/qte77/polyfetch-scrape/issues/30)
  ([RFC 7725](https://datatracker.ietf.org/doc/html/rfc7725))
- Surface permanent redirects (301/308) on `Response` so callers can update
  stored URLs — [#31](https://github.com/qte77/polyfetch-scrape/issues/31)
  ([RFC 9110 §15.4.2](https://datatracker.ietf.org/doc/html/rfc9110#section-15.4.2),
  [RFC 7538](https://datatracker.ietf.org/doc/html/rfc7538))
- Document the taxonomy in `docs/scraping-landscape.md` — [#34](https://github.com/qte77/polyfetch-scrape/issues/34)

## 0.4.0 — API Wrappers

Domain-specific wrappers for document APIs.

**Goals**:

- arXiv bulk download (OAI-PMH + direct PDF)
- USPTO full-text search and patent PDF retrieval
- EUR-Lex SPARQL/REST queries
- legislation.gov.uk REST API
- WIPO PATENTSCOPE REST API
- GitHub source wrapper (gh CLI / REST) — [#32](https://github.com/qte77/polyfetch-scrape/issues/32)
- Sitemap-based URL discovery helper for source wrappers — [#33](https://github.com/qte77/polyfetch-scrape/issues/33)

## 0.5.0 — LLM-Ready Output

Structured Markdown and JSON extraction for downstream LLM consumption.

**Goals**:

- HTML-to-Markdown conversion with metadata preservation
- JSON schema for structured document fields (title, abstract, sections, citations)
- Clean text extraction (strip boilerplate, navigation, ads)
