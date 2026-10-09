<!-- markdownlint-disable MD013 -->
# Using polyfetch-scrape without installing it

Machine-facing usage contract for **calling polyfetch from another project or agent without installing it** (no venv poison). Human overview: [`README.md`](README.md). Dev workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## TL;DR — one command

```bash
uv run --directory <polyfetch> polyfetch fetch <url> --json
```

- `<polyfetch>` = your checkout of this repo — a git submodule (e.g. `vendor/polyfetch-scrape`) or a sibling clone.
- Runs in the clone's **own** `.venv` (auto-synced from its lock on first run). Your environment is never touched.
- Hide the ceremony: `alias polyfetch='uv run --directory <polyfetch> polyfetch'`.

## Why env-borrow (not `uv add`)

- `uv add git+https://github.com/qte77/polyfetch-scrape` (it is not on PyPI) pulls polyfetch **and its heavy deps** (patchright, curl_cffi, httpx) into *your* lockfile → poison.
- `uv run --directory <polyfetch> …` keeps all of that inside the clone. Two ways to consume:
  - **out-of-process** (recommended for agents): call the CLI, parse `--json`.
  - **in-clone script**: `uv run --directory <polyfetch> python /abs/path/script.py` → full Python API, run with the clone's interpreter. Pass **absolute paths** — `--directory` makes CWD the clone.

## Scripting substrate

Beyond the CLI, polyfetch is a **substrate you script against**: `render_session(url)` hands you the live, instrumented stealth-Patchright `Page` as `.page`, with the **full Chromium DevTools / CDP surface** — for flows the CLI doesn't cover.

`render_session(url, *, wait_until=..., timeout=30.0, device=None, viewport=None, color_scheme=None, user_agent=None, locale=None, record_video_dir=None, record_video_size=None, record_har_path=None, record_har_mode="minimal", record_har_content="omit") -> RenderSession` — `viewport`/`record_video_size` are plain `(width, height)` pixel tuples, **not** a `RenderOptions`/dict. `record_har_path` records a HAR 1.2 file of every request — **contains every request/response header, including cookies**; see the security note below. Full signature + semantics: [`docs/api-reference.md` § Render session](docs/api-reference.md#render-session-interactive-patchright-tier).

### DevTools capture (console, network, JS errors)

Attach any `page.on(...)` listener and react to the browser's DevTools events as the page runs — the same signals you'd read in the Chrome DevTools console/network panels:

```python
with render_session(url) as s:
    s.page.on("console", lambda m: print(m.type, m.text))  # console.log / warn / error
    s.page.on("pageerror", lambda e: print("uncaught JS:", e))  # uncaught JS exceptions
    s.page.on("requestfailed", lambda r: print(r.url, r.failure))  # failed network requests
    s.click_text("Load more")  # …then drive the page
```

You don't even have to wire listeners: capture is **always on out of the box** — `s.console_errors`
(console errors + uncaught JS errors) and `s.network_failures` (failed / `≥400` requests) fill for the
whole session, initial page load included. On the one-shot `fetch()` tier the same capture is opt-in
via `RenderOptions(capture_console=True, capture_network_failures=True)` → `Response.console_errors` /
`Response.network_failures`.

> **Caveat:** a headless capture reflects only *this* runner's network — a failure a real user hits
> (CORS / a browser extension / a proxy) can succeed here and read clean. Treat an empty capture as
> "no error *on this network*", not "no error".
>
> **Caveat:** `page.evaluate` runs in an **isolated world** under Patchright. The DOM is shared, but
> globals defined by the page's own scripts (`window.Chart`, `window.THREE`, module-scoped vars) read
> back `undefined` even when they exist and work. This fails *silently* — `evaluate` returns
> `undefined` rather than raising, so an assertion on page state yields a confident, wrong "it did not
> render". Use **screenshots as ground truth** for "did it render", `page.on(...)` for "did it load",
> and reserve `evaluate` for DOM you set or read structurally (element presence, attributes,
> `textContent`).

### Other `.page` recipes

```python
with render_session(url) as s:
    snap = s.page.locator("body").aria_snapshot()  # accessibility tree of the page
```

(`aria_snapshot()` is the current Patchright API; `page.accessibility.snapshot()` was removed upstream.) polyfetch owns the browser install, launch/teardown, capture, and SSRF guard; you own the app-specific steps. See README's [Two layers](README.md#two-layers-engine--scripting-substrate) for the full engine/scripts split. For more worked recipes (multi-step walks, live emulation, what not to do), see the [scripting cookbook](docs/scripting.md).

## Commands

| Invocation | Purpose |
|---|---|
| `polyfetch fetch <url> --json` | one URL → JSON summary (below) |
| `polyfetch fetch <url> --show-body` | raw response **bytes** to stdout (binary-safe; takes precedence over `--json`) |
| `polyfetch bulk <file> [--workers N]` | one URL per line (`#`/blank skipped) → JSON-lines |
| `polyfetch discover <url> [--json]` | structured entrypoints (sitemaps/feeds/`llms.txt`/JSON-LD `@type`s) → JSON |
| `polyfetch doctor [--fix]` | check the browser-tier Chromium is installed (exit non-zero if missing); `--fix` installs it. Handy when borrowing this venv — the Chromium cache can get wiped |
| `polyfetch devices` | list the device presets usable with `fetch --device`, one per line |
| `polyfetch --help` / `polyfetch --version` | discover the surface / print version |

`fetch` flags: `--tier httpx|curl_cffi|patchright` (pin one backend, skip fallback), `--min-tier`/`--max-tier httpx|curl_cffi|patchright` (bound the fallback range; `--max-tier curl_cffi` never launches a browser), `--max-attempts N`, `--timeout S`, `--browser chrome|firefox`, `--method`, `--etag STR` / `--if-modified-since STR` (conditional GET → `If-None-Match` / `If-Modified-Since`; `304` on a match), `--json`, `--show-body`.

`fetch` **request body flags:** `--json-body VALUE` (parsed with `json.loads`, sent as `fetch()`'s `json=`) or `--data VALUE` (sent raw as `fetch()`'s `content=`) — mutually exclusive (`exit 2` if both are given). `VALUE` is a literal string, `@path` to read a file, or `@-` to read stdin — handy for a large payload. Invalid JSON in `--json-body` exits `2` with a parse-error message. Both flags are httpx/curl_cffi-tier only: the patchright tier is GET-only and raises a clear `FetchError` if either is combined with `--tier patchright` (or an auto-escalation would reach it).

`fetch` **patchright-tier render flags:** `--wait-until domcontentloaded|load|networkidle`, `--wait-for-selector CSS`, `--wait-for-function JS`, `--screenshot viewport|full_page|<css>` + `--screenshot-out PATH` (writes the PNG). With `--json`, the PNG is also surfaced inline as base64 `screenshot_b64` (no file needed) — see the schema below.

`fetch` **patchright-tier emulation + video flags:** `--device NAME` (a Patchright device preset, e.g. `"iPhone 13"` — list them with `polyfetch devices`; an unknown name exits `2` and suggests near-misses), `--device-json '<json object>'` (a custom device bundle for a device the registry doesn't carry, e.g. `'{"user_agent": "…", "viewport": {"width": 411, "height": 914}, "is_mobile": true}'` — mutually exclusive with `--device`), `--viewport WxH` (e.g. `1280x720`), `--color-scheme light|dark|no-preference`, `--user-agent STR`, `--locale STR` (BCP 47, e.g. `en-US`), `--video-out DIR` (records a VP8 `.webm` of the session into `DIR`; the finished path lands on `Response.video_path` and, with `--json`, is surfaced as `video_path` — the exact auto-generated filename).

`fetch` **patchright-tier HAR flag:** `--har-out FILE` (records a HAR 1.2 file of every request the session makes, to that exact path; the path lands on `Response.har_path` and, with `--json`, is surfaced as `har_path`). Defaults to `"minimal"` mode and omitted response bodies.

> **Security — HAR files contain credentials.** A HAR records every request/response header,
> including `Cookie` and `Authorization`. It is safe today because polyfetch has no
> authenticated-session support yet, but once one lands (#200/#178) a HAR taken during a
> logged-in session **will** contain live credentials. Never commit, upload, or share a `--har-out`
> file uninspected — treat it like a secret. Bodies are omitted by default; headers are not
> redacted (tracked as a follow-up).

`bulk` flags: `--workers N` (concurrency), `--delay S` (per-host polite spacing — min seconds between same-host requests, shared across workers), `--timeout S`, `--max-attempts N`, `--json`/`--text` (default `--json`, JSON-lines).

(The optional `contrib` scanner `polyfetch easter-hunt scan` is unsupported and out of this contract — see [`CONTRIBUTING.md`](CONTRIBUTING.md).)

## Output schema (`--json`)

`fetch --json` and every `bulk` line emit:

```json
{"url": "https://…", "status": 200, "backend": "curl_cffi", "bytes": 179447, "content_type": "text/html; charset=utf-8"}
```

- `backend` = which tier answered (`httpx` → `curl_cffi` → `patchright`).
- `request_user_agent` (fetch **and** every `bulk` line) = the `User-Agent` actually sent, when the
  backend can tell cheaply; present on httpx/curl_cffi (the merged outgoing headers) when it's known,
  absent when it isn't (curl_cffi's `impersonate=` profile injects its own browser-matching UA
  natively and doesn't expose it in Python unless you override it yourself); on patchright, present
  when `--user-agent`/`--device` set it, absent otherwise (the browser's own default isn't probed).
  See the security note below this schema for why a `200` here is not proof a site is open to every
  client.
- `screenshot_b64` (fetch `--json` only) = base64-encoded PNG, present **only** when a screenshot was
  captured (`--screenshot` on the patchright tier); the key is absent otherwise. Decode with
  `jq -r .screenshot_b64 | base64 -d`.
- `video_path` (fetch `--json` only) = filesystem path to the recorded `.webm`, present **only** when
  `--video-out DIR` recorded one on the patchright tier; absent otherwise.
- `har_path` (fetch `--json` only) = filesystem path to the recorded HAR 1.2 file, present **only**
  when `--har-out FILE` recorded one on the patchright tier; absent otherwise. See the security
  note above before sharing this file.
- `permanent_redirect_to` (fetch **and** every `bulk` line) = the `Location` target of a **permanent**
  redirect (301/308), present **only** when the response was one; absent otherwise. polyfetch does not
  auto-follow redirects (SSRF-safe, transparent), so on a 301 you get `status:301, bytes:0` — read this
  key and re-fetch the target yourself. Temporary redirects (302/303/307) never set it.
- Need the page content, not metadata? use `--show-body`.

> **UA substitution — a `200` is not proof a site is open to every client.** The httpx tier
> defaults to a real desktop-browser `User-Agent` from `utils/http_ua.STABLE_USER_AGENT`
> (rotated quarterly; see that module's docstring) instead of httpx's own `python-httpx/…`
> string — a deliberate anti-fingerprint choice (#198). That means `fetch(url)` with no
> explicit UA answers "is this reachable **pretending to be Chrome**", not "is this reachable
> at all": a site that 403s a bare `curl`/`python-urllib` request can still return `200` here,
> and the delta is the UA, not the transport. If you're *characterizing* a target's bot policy
> rather than scraping it, pass your own `headers={"User-Agent": "..."}` (or an empty one) and
> read `request_user_agent` back to confirm what was actually sent.

`discover --json` emits the structured entrypoints a site advertises (empty arrays when none):

```json
{"url": "https://…", "sitemaps": [], "event_sitemaps": [], "feeds": [], "llms_txt": [], "json_ld_types": []}
```

## Errors & exit codes

- Success → exit `0`. Failure → exit `1` (`bulk` exits `1` if **any** URL failed).
- On `--json`, both `fetch` (**stdout**) and every failed `bulk` line emit the same error schema:

```json
{"url": "https://…", "error_type": "GoneError", "status": 404, "message": "terminal HTTP 404: https://…"}
```

- `error_type` = the exception class (below); `status` = terminal HTTP code, or `null` when not status-bound (e.g. retries exhausted).
- `headers` / `body_excerpt` (optional) = the **final tier's** blocked/exhausted response, when captured: `headers` is that response's headers (`Set-Cookie` always redacted — never a request header/cookie), `body_excerpt` is its body truncated to 2 KB and decoded lossily. Both keys are **absent** (not `null`) when not captured, so existing `--json` consumers are unaffected. Lets you tell a pure TLS/fingerprint block from a session/behavioral one without dropping to `render_session` (see #209):

```json
{"url": "https://…", "error_type": "FingerprintBlock", "status": 403, "message": "…", "headers": {"content-type": "text/html"}, "body_excerpt": "<html>…</html>"}
```

- Without `--json`, `fetch` prints `<ErrorType>: <message>` to **stderr**.
- Terminal statuses — no retry, no escalation. Exception names (all subclass `FetchError`): `AuthRequired` (401/407), `GoneError` (404/410), `LegalBlock` (451).
- **A `GET` + 2xx (not `204`) + empty body + HTML-or-missing `Content-Type` is a suspected soft block**, not a success: some anti-bot layers return an empty `200` instead of an explicit `403`. It escalates like a `403` does; the last tier raises `FingerprintBlock` instead of returning the empty `Response` — including when that tier was pinned with `--tier` (the same as a `403` on a pinned tier today). `HEAD`, `304`, `204`, and a non-HTML content type (`application/json`, `text/plain`, …) are never affected — see [#237](https://github.com/qte77/polyfetch-scrape/issues/237).

## Fallback tiers (automatic)

`fetch(url)` tries httpx → curl_cffi (browser TLS/JA3) → Patchright (headless Chromium); `--tier` pins one. Tier 3 needs the browser binary **once, in the clone**:

```bash
uv run --directory <polyfetch> patchright install chromium   # ~300 MB; tiers 1–2 don't need it
```

Not on Alpine/musl, though — patchright has no `musllinux` wheel there. `polyfetch doctor` detects this and exits non-zero with the workaround instead of a cryptic launch failure; see [`docs/api-reference.md`](docs/api-reference.md#cli-only-commands). Tiers 1–2 (httpx, curl_cffi) are unaffected.

## Gotchas

- **Extra deps for an in-clone script**: `uv run --directory <polyfetch> --with <dep> python /abs/script.py` — ephemeral, never touches the clone's lock.
- **Harmless warning** when run from inside your own activated venv: `VIRTUAL_ENV=… does not match the project environment … will be ignored`. Informational.
- **Editor/type support without installing**: point pyright `extraPaths` at `<polyfetch>/src`; execute via `uv run --directory`.
- **SSRF guard is escalation-only, and only on the discovery paths.** `discover()` /
  `polyfetch discover`, `utils.sitemap.fetch_sitemap_urls()`, and the `easter-hunt`
  contrib follow attacker-influenced URLs (sitemap entries, feed links, JSON-LD). The
  **seed** you pass in — the `url`/`domain`/seed argument — is **never blocked**, even
  a literal internal IP or `localhost`: pointing these at a local dev server is
  intentional and supported. Only a URL the tool *derives* from that seed (a probed
  path, a redirect target) is checked, and only when the seed itself is external — an
  internal seed means you already trust everything reachable from it. Plain `fetch()`
  is **not** guarded at all. Full guard description (the allowlist classification,
  fail-open resolver behaviour, the preventive-vs-post-hoc redirect check per tier):
  [architecture.md](docs/architecture.md)'s `utils/_ssrf.py` row.

  **Relaxed from an earlier version of this guard:** a literal internal-IP or
  `localhost` seed used to be rejected outright; it is now always allowed (owner
  decision, 2026-09-30) — `discover("http://localhost:8080")` and
  `discover("http://127.0.0.1:8080")` both work.

## Stable surface (what you may depend on)

- **Stable**: the `polyfetch` CLI + its `--json` schema; the top-level `polyfetch_scrape` public names (`fetch`, `render_session`, `Response`, `RenderOptions`, `RenderAction`, `Screenshot`, `RetryPolicy`, `FetchError` + subclasses). `render_session` is Python-only (managed multi-step browser sessions; not CLI-expressible).
- **Off-limits**: `polyfetch_scrape._backends/*` (private, will churn); `polyfetch_scrape.contrib/*` (optional, unsupported).
