<!-- markdownlint-disable MD033 -->
# polyfetch-scrape

> HTTP scraping toolkit: typed `Response`, three-tier fallback chain (httpx → curl_cffi → Patchright), opt-in e2e tests, typer CLI.

Reusable Python library + CLI that abstracts the "which tool beats which anti-bot" decision: callers just `fetch(url)` and get back a typed `Response` regardless of which backend ultimately succeeded.

**I am a:** [Library user](#quick-start-library) | [CLI user](#quick-start-cli) | [Contributor](#development)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.4.0-informational)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-%3E=3.11-blue)](pyproject.toml)
[![CodeFactor](https://www.codefactor.io/repository/github/qte77/polyfetch-scrape/badge)](https://www.codefactor.io/repository/github/qte77/polyfetch-scrape)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## When to reach for this

Claude Code's built-in WebFetch tool exposes no header parameters in its public schema, so callers cannot customize `User-Agent`, `Accept`, or `Referer`. Empirically its default UA is rejected (HTTP 403) by sites with non-trivial bot detection — `hamiltoncompany.com`, `thingiverse.com`, `web.archive.org` are concrete examples observed in agent sessions. `polyfetch-scrape` is the next rung: browser-shape headers in the cheap tier, real TLS impersonation in the middle tier, headless Chromium with anti-detection patches in the fallback tier.

## Quick Start (library)

```bash
uv add polyfetch-scrape
uv run patchright install chromium   # one-off; required only for the Playwright tier
```

```python
from polyfetch_scrape import fetch

r = fetch("https://nowsecure.nl/")
print(r.status, r.backend, len(r.body))     # 200 curl_cffi 179447
```

## Quick Start (CLI)

```bash
polyfetch fetch https://example.com
polyfetch fetch https://example.com --json
polyfetch fetch https://httpbin.org/user-agent --show-body   # verify the UA you send
polyfetch fetch https://quotes.toscrape.com/js/ --tier playwright   # force the JS-render tier
polyfetch bulk urls.txt --workers 4
polyfetch --help
```

## Fallback Chain

| Tier | Backend | When it engages |
|---|---|---|
| 1 | `httpx` | every request first |
| 2 | `curl_cffi` (chrome impersonation) | tier 1 returns 403 or hits a TLS error |
| 3 | Patchright (headless Chromium) | tier 2 also blocked |

`Response.backend` reflects which tier succeeded. See [`docs/scraping-landscape.md`](docs/scraping-landscape.md) for empirical findings (with first-party citations) on what each tier actually beats in practice.

**Try it:** `make demo_tiers` drives each backend directly to show what its tier uniquely provides (a TLS/JA3 fingerprint diff + a JS render). [`examples/fallback-tier-targets.txt`](examples/fallback-tier-targets.txt) lists ToS-safe targets per tier difficulty (Tier 1 → Ceiling) — run the whole ladder with `make probe_bulk FILE=examples/fallback-tier-targets.txt` (it exits non-zero: the two Ceiling targets 403 by design; add `MAX_ATTEMPTS=1` to fail fast).

## Public API

```python
fetch(url, *, method="GET", headers=None, timeout=30.0, retry=None,
      browser="chrome", wait_for_selector=None, tier=None,
      etag=None, last_modified=None, render=None) -> Response
      # tier pins one backend: "httpx"|"curl_cffi"|"playwright"
      # etag / last_modified → If-None-Match / If-Modified-Since (conditional GET)
      # render=RenderOptions(...) → playwright-tier wait/screenshot controls

RenderOptions(wait_until="domcontentloaded"|"load"|"networkidle", wait_for_selector=None,
              wait_for_function=None, screenshot=None)
      # playwright tier only; screenshot="viewport"|"<css-selector>" → Response.screenshot (PNG bytes)

Response(url, status, headers, body, content_type, backend,
         permanent_redirect_to=None, screenshot=None)
      # permanent_redirect_to: Location target on a 301/308, so callers can update stored URLs
      # screenshot: PNG bytes when requested on the playwright tier, else None
RetryPolicy(max_attempts=3, backoff_initial=0.2, backoff_factor=2.0,
            retry_on_status=frozenset({429, 500, 502, 503, 504}))

# Public exceptions (all subclass FetchError). Terminal statuses raise on the first
# attempt in every tier — no retry, no escalation:
FetchError       # base: retries exhausted on every tier
AuthRequired     # 401 / 407
GoneError        # 404 / 410
LegalBlock       # 451 (RFC 7725) — never escalated to the fingerprint tiers
```

The library logs tier escalations on the `polyfetch_scrape` logger (silent by default via a `NullHandler`) — configure logging in your app to observe which tier each request escalated through.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full command reference, dev workflow, and pre-commit checklist. Quick start: `make setup_dev && make validate`.

For AI agent behavioural rules, see [`AGENTS.md`](AGENTS.md). For release notes, see [`CHANGELOG.md`](CHANGELOG.md).

## Project Outline

Three-tier sync `fetch()` library wrapped by a thin typer CLI. Code lives under `src/polyfetch_scrape/`; the three backends are isolated in private `_backends/` (`httpx_backend.py`, `curl_backend.py`, `playwright_backend.py`); opt-in extras live under `contrib/` (e.g. `easter_hunt`, a page-artifact scanner exposed as `polyfetch easter-hunt scan`) and consume the public `fetch()` — unsupported, core never depends on them. Roadmap and architecture: [`docs/roadmap.md`](docs/roadmap.md). Tool landscape and empirical anti-bot findings: [`docs/scraping-landscape.md`](docs/scraping-landscape.md).

## References

- [Roadmap](docs/roadmap.md) — staged delivery plan (0.1 → 0.5)
- [Scraping landscape](docs/scraping-landscape.md) — tool comparison + empirical findings
- [gha-rxiv-feed-action](https://github.com/qte77/gha-rxiv-feed-action) — fetch arXiv/bioRxiv/medRxiv feeds (open APIs; polyfetch's fallback chain isn't needed for these)
- [Changelog](CHANGELOG.md) — release notes (Keep a Changelog format)
- [Codespaces — qte77/polyforge-orchestrator/docs/codespaces.md](https://github.com/qte77/polyforge-orchestrator/blob/main/docs/codespaces.md) — canonical cross-qte77 reference for Codespaces auth, token precedence, GPG signing, devcontainer lifecycle
- [License](LICENSE) (Apache-2.0) and [Notice](NOTICE)
