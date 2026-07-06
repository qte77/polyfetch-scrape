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

## Commands

| Invocation | Purpose |
|---|---|
| `polyfetch fetch <url> --json` | one URL → JSON summary (below) |
| `polyfetch fetch <url> --show-body` | raw response **bytes** to stdout (binary-safe; takes precedence over `--json`) |
| `polyfetch bulk <file> [--workers N]` | one URL per line (`#`/blank skipped) → JSON-lines |
| `polyfetch --help` / `polyfetch --version` | discover the surface / print version |

`fetch` flags: `--tier httpx|curl_cffi|playwright` (pin one backend, skip fallback), `--max-attempts N`, `--timeout S`, `--browser chrome|firefox`, `--wait-for-selector CSS` (playwright only), `--method`, `--json`, `--show-body`.

`bulk` flags: `--workers N` (concurrency), `--timeout S`, `--max-attempts N`, `--json`/`--text` (default `--json`, JSON-lines).

(The optional `contrib` scanner `polyfetch easter-hunt scan` is unsupported and out of this contract — see [`CONTRIBUTING.md`](CONTRIBUTING.md).)

## Output schema (`--json`)

`fetch --json` and every `bulk` line emit:

```json
{"url": "https://…", "status": 200, "backend": "curl_cffi", "bytes": 179447, "content_type": "text/html; charset=utf-8"}
```

- `backend` = which tier answered (`httpx` → `curl_cffi` → `playwright`).
- Need the page content, not metadata? use `--show-body`.

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

- **Stable**: the `polyfetch` CLI + its `--json` schema; the top-level `polyfetch_scrape` public names (`fetch`, `Response`, `RenderOptions`, `RetryPolicy`, `FetchError` + subclasses).
- **Off-limits**: `polyfetch_scrape._backends/*` (private, will churn); `polyfetch_scrape.contrib/*` (optional, unsupported).
