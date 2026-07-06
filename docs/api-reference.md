<!-- markdownlint-disable MD033 -->
# Public API reference

The complete public surface of `polyfetch_scrape`. Everything under `_backends/` is private; only the names below are importable from the package root (`from polyfetch_scrape import fetch, Response, RenderOptions, RenderAction, RetryPolicy, FetchError, ...`).

## `fetch`

```python
fetch(url, *, method="GET", headers=None, timeout=30.0, retry=None,
      browser="chrome", wait_for_selector=None, tier=None,
      etag=None, last_modified=None, json=None, content=None,
      render=None) -> Response
      # tier pins one backend: "httpx"|"curl_cffi"|"playwright"
      # etag / last_modified → If-None-Match / If-Modified-Since (conditional GET)
      # json=<obj> / content=<bytes> → POST/PUT request body (mutually exclusive)
      # render=RenderOptions(...) → playwright-tier wait/screenshot controls
```

A single call runs the three-tier fallback chain (or the pinned `tier`) and returns a typed `Response` regardless of which backend succeeded.

**Request bodies (`json` / `content`) use the httpx and curl_cffi tiers only.** The playwright tier is GET-only and cannot replay a body, so a body request that would otherwise escalate to playwright — or one pinned to `tier="playwright"` — raises `FetchError` instead of silently dropping the body. Passing both `json` and `content` also raises `FetchError`. POST is not idempotent, but body requests are still retried on the same connection/timeout + `retry_on_status` conditions as any other request.

## Render controls (playwright tier)

```python
RenderOptions(wait_until="domcontentloaded"|"load"|"networkidle", wait_for_selector=None,
              wait_for_function=None, screenshot=None, actions=())
      # playwright tier only; screenshot="viewport"|"<css-selector>" → Response.screenshot (PNG bytes)
      # actions=(RenderAction(...), ...) run in order BEFORE waits/capture (drive → settle → capture)

RenderAction(verb, selector=None, text=None, value=None, ms=None)
      # verb: "click"(selector) | "click_text"(text) | "fill"(selector,value)
      #     | "wait_for_selector"(selector) | "wait_ms"(ms)
```

## `Response` and `RetryPolicy`

```python
Response(url, status, headers, body, content_type, backend,
         permanent_redirect_to=None, screenshot=None)
      # permanent_redirect_to: Location target on a 301/308, so callers can update stored URLs
      # screenshot: PNG bytes when requested on the playwright tier, else None

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

## Logging

The library logs tier escalations on the `polyfetch_scrape` logger (silent by default via a `NullHandler`) — configure logging in your app to observe which tier each request escalated through.
