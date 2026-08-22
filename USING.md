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

- `uv add polyfetch-scrape` pulls polyfetch **and its heavy deps** (patchright, curl_cffi, httpx) into *your* lockfile → poison.
- `uv run --directory <polyfetch> …` keeps all of that inside the clone. Two ways to consume:
  - **out-of-process** (recommended for agents): call the CLI, parse `--json`.
  - **in-clone script**: `uv run --directory <polyfetch> python /abs/path/script.py` → full Python API, run with the clone's interpreter. Pass **absolute paths** — `--directory` makes CWD the clone.

## Scripting substrate

Beyond the CLI, polyfetch is a **substrate you script against**: `render_session(url)` hands you the live, instrumented stealth-Patchright `Page` as `.page`, with the **full Chromium DevTools / CDP surface** — for flows the CLI doesn't cover.

### DevTools capture (console, network, JS errors)

Attach any `page.on(...)` listener and react to the browser's DevTools events as the page runs — the same signals you'd read in the Chrome DevTools console/network panels:

```python
with render_session(url) as s:
    s.page.on("console", lambda m: print(m.type, m.text))          # console.log / warn / error
    s.page.on("pageerror", lambda e: print("uncaught JS:", e))     # uncaught JS exceptions
    s.page.on("requestfailed", lambda r: print(r.url, r.failure))  # failed network requests
    s.click_text("Load more")                                      # …then drive the page
```

You don't even have to wire listeners: capture is **always on out of the box** — `s.console_errors`
(console errors + uncaught JS errors) and `s.network_failures` (failed / `≥400` requests) fill for the
whole session, initial page load included. On the one-shot `fetch()` tier the same capture is opt-in
via `RenderOptions(capture_console=True, capture_network_failures=True)` → `Response.console_errors` /
`Response.network_failures`.

> **Caveat:** a headless capture reflects only *this* runner's network — a failure a real user hits
> (CORS / a browser extension / a proxy) can succeed here and read clean. Treat an empty capture as
> "no error *on this network*", not "no error".

### Other `.page` recipes

```python
with render_session(url) as s:
    snap = s.page.locator("body").aria_snapshot()   # accessibility tree of the page
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
| `polyfetch --help` / `polyfetch --version` | discover the surface / print version |

`fetch` flags: `--tier httpx|curl_cffi|patchright` (pin one backend, skip fallback), `--min-tier`/`--max-tier httpx|curl_cffi|patchright` (bound the fallback range; `--max-tier curl_cffi` never launches a browser), `--max-attempts N`, `--timeout S`, `--browser chrome|firefox`, `--method`, `--etag STR` / `--if-modified-since STR` (conditional GET → `If-None-Match` / `If-Modified-Since`; `304` on a match), `--json`, `--show-body`.

`fetch` **patchright-tier render flags:** `--wait-until domcontentloaded|load|networkidle`, `--wait-for-selector CSS`, `--wait-for-function JS`, `--screenshot viewport|full_page|<css>` + `--screenshot-out PATH` (writes the PNG). With `--json`, the PNG is also surfaced inline as base64 `screenshot_b64` (no file needed) — see the schema below.

`fetch` **patchright-tier emulation + video flags:** `--device NAME` (a Patchright device preset, e.g. `"iPhone 13"`), `--viewport WxH` (e.g. `1280x720`), `--color-scheme light|dark|no-preference`, `--user-agent STR`, `--locale STR` (BCP 47, e.g. `en-US`), `--video-out DIR` (records a VP8 `.webm` of the session into `DIR`; the finished path lands on `Response.video_path` and, with `--json`, is surfaced as `video_path` — the exact auto-generated filename).

`bulk` flags: `--workers N` (concurrency), `--delay S` (per-host polite spacing — min seconds between same-host requests, shared across workers), `--timeout S`, `--max-attempts N`, `--json`/`--text` (default `--json`, JSON-lines).

(The optional `contrib` scanner `polyfetch easter-hunt scan` is unsupported and out of this contract — see [`CONTRIBUTING.md`](CONTRIBUTING.md).)

## Output schema (`--json`)

`fetch --json` and every `bulk` line emit:

```json
{"url": "https://…", "status": 200, "backend": "curl_cffi", "bytes": 179447, "content_type": "text/html; charset=utf-8"}
```

- `backend` = which tier answered (`httpx` → `curl_cffi` → `patchright`).
- `screenshot_b64` (fetch `--json` only) = base64-encoded PNG, present **only** when a screenshot was
  captured (`--screenshot` on the patchright tier); the key is absent otherwise. Decode with
  `jq -r .screenshot_b64 | base64 -d`.
- `video_path` (fetch `--json` only) = filesystem path to the recorded `.webm`, present **only** when
  `--video-out DIR` recorded one on the patchright tier; absent otherwise.
- `permanent_redirect_to` (fetch `--json` only) = the `Location` target of a **permanent** redirect
  (301/308), present **only** when the response was one; absent on temporary redirects (302/303/307)
  and non-redirects. Read it with `jq -r .permanent_redirect_to` to update a stored URL.
- Need the page content, not metadata? use `--show-body`.

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
- Without `--json`, `fetch` prints `<ErrorType>: <message>` to **stderr**.
- Terminal statuses — no retry, no escalation. Exception names (all subclass `FetchError`): `AuthRequired` (401/407), `GoneError` (404/410), `LegalBlock` (451).

## Fallback tiers (automatic)

`fetch(url)` tries httpx → curl_cffi (browser TLS/JA3) → Patchright (headless Chromium); `--tier` pins one. Tier 3 needs the browser binary **once, in the clone**:

```bash
uv run --directory <polyfetch> patchright install chromium   # ~300 MB; tiers 1–2 don't need it
```

## Gotchas

- **Extra deps for an in-clone script**: `uv run --directory <polyfetch> --with <dep> python /abs/script.py` — ephemeral, never touches the clone's lock.
- **Harmless warning** when run from inside your own activated venv: `VIRTUAL_ENV=… does not match the project environment … will be ignored`. Informational.
- **Editor/type support without installing**: point pyright `extraPaths` at `<polyfetch>/src`; execute via `uv run --directory`.

## Stable surface (what you may depend on)

- **Stable**: the `polyfetch` CLI + its `--json` schema; the top-level `polyfetch_scrape` public names (`fetch`, `render_session`, `Response`, `RenderOptions`, `RenderAction`, `Screenshot`, `RetryPolicy`, `FetchError` + subclasses). `render_session` is Python-only (managed multi-step browser sessions; not CLI-expressible).
- **Off-limits**: `polyfetch_scrape._backends/*` (private, will churn); `polyfetch_scrape.contrib/*` (optional, unsupported).
