# polyfetch-scrape

> HTTP scraping toolkit: typed `Response`, three-tier fallback chain (httpx → curl_cffi → Patchright), opt-in e2e tests, typer CLI.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.5.0-informational)](CHANGELOG.md)
[![Test](https://github.com/qte77/polyfetch-scrape/actions/workflows/test.yml/badge.svg)](https://github.com/qte77/polyfetch-scrape/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-%3E=3.11-blue)](pyproject.toml)
[![CodeFactor](https://www.codefactor.io/repository/github/qte77/polyfetch-scrape/badge)](https://www.codefactor.io/repository/github/qte77/polyfetch-scrape)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

## What

- **One call, typed result.** `fetch(url)` returns a typed `Response` (`status`, `body`, `backend`, …) no matter which backend succeeded — you never pick a scraping tool per site.
- **Three-tier fallback, reactive.** `httpx` → `curl_cffi` (Chrome TLS/JA3 impersonation) → Patchright (headless Chromium, anti-detection). Escalates only on a real `403` or TLS block, so the cheap tier is always tried first.
- **Beats blocks a UA swap can't.** Real TLS impersonation + a headless-Chromium fallback clear sites that reject header-only spoofing ([empirical findings](docs/scraping-landscape.md)).
- **Typed error taxonomy.** Terminal statuses (`401/407/404/410/451`) raise typed exceptions; `429/5xx` retry honouring `Retry-After`.
- **Conditional GET + render controls.** `etag`/`last_modified` for `304`s; playwright-tier waits, screenshots, and scripted actions.
- **Library, CLI, or env-borrow.** `import fetch`, run `polyfetch`, or sideload from another repo/agent without installing ([USING.md](USING.md)).

## How

**I am a:** [Library user](#library) | [CLI user](#cli) | [Agent / sideload](USING.md) | [Contributor](#development)

### Install

```bash
uv add polyfetch-scrape
uv run patchright install chromium   # one-off; required only for the Playwright tier
```

### Library

```python
from polyfetch_scrape import fetch

r = fetch("https://nowsecure.nl/")
print(r.status, r.backend, len(r.body))     # 200 curl_cffi 179447
```

### CLI

```bash
polyfetch fetch https://example.com
polyfetch fetch https://example.com --json
polyfetch fetch https://httpbin.org/user-agent --show-body   # verify the UA you send
polyfetch fetch https://example.com --etag '"abc123"'   # conditional GET (If-None-Match → 304 on match)
polyfetch fetch https://quotes.toscrape.com/js/ --tier playwright   # force the JS-render tier
polyfetch fetch https://example.com --max-tier curl_cffi   # cap escalation — never launch a browser
polyfetch fetch https://quotes.toscrape.com/js/ --tier playwright --screenshot viewport --screenshot-out shot.png   # render + screenshot
polyfetch bulk urls.txt --workers 4 --delay 0.5   # 4 workers, ≥0.5s between same-host requests
polyfetch --help
```

**Consuming polyfetch from another project or an agent without installing it?** See [`USING.md`](USING.md) — the `uv run --directory` env-borrow contract (no venv poison).

### Fallback chain

| Tier | Backend | When it engages |
|---|---|---|
| 1 | `httpx` | every request first |
| 2 | `curl_cffi` (chrome impersonation) | tier 1 returns 403 or hits a TLS error |
| 3 | Patchright (headless Chromium) | tier 2 also blocked |

`Response.backend` reflects which tier succeeded. `make demo_tiers` drives each backend directly to show what its tier uniquely provides (a TLS/JA3 fingerprint diff + a JS render); [`examples/fallback-tier-targets.txt`](examples/fallback-tier-targets.txt) lists ToS-safe targets per tier difficulty — run the ladder with `make probe_bulk FILE=examples/fallback-tier-targets.txt`.

### Public API

`fetch(url, *, …) -> Response` plus `render_session(url)` (managed multi-step interactive browser sessions), `RenderOptions`, `RenderAction`, `Response`, `RetryPolicy`, and the `FetchError` exception hierarchy. **Full signatures and options: [`docs/api-reference.md`](docs/api-reference.md).**

### Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full command reference, dev workflow, and pre-commit checklist. Quick start: `make setup_dev && make validate`. For AI-agent behavioural rules, see [`AGENTS.md`](AGENTS.md); for release notes, [`CHANGELOG.md`](CHANGELOG.md).

### Versioning

Two-step release pipeline (GitHub Actions), mirroring the qte77 sibling repos:

1. **Bump** — run the **Bump version** workflow (`workflow_dispatch`; pick major/minor/patch). It bumps `pyproject.toml`, the `uv.lock` self-reference, the README badge, and rolls `CHANGELOG.md` (new dated section + compare link) via [`bump-my-version`](https://github.com/callowayproject/bump-my-version), then opens a `chore(release)` PR.
2. **Tag + release** — **merge that PR with a PAT** (a `GITHUB_TOKEN` push won't re-trigger workflows). The **Tag and Release** workflow then tags `vX.Y.Z` on the merge commit and publishes the GitHub Release from the matching `CHANGELOG.md` section.

Keep new changes under `## [Unreleased]`; the bump rolls them into the dated version section.

## Why

Claude Code's built-in **WebFetch** exposes no header parameters in its public schema, so callers cannot set `User-Agent`, `Accept`, or `Referer` — and its default UA is empirically rejected (HTTP 403) by sites with non-trivial bot detection (`hamiltoncompany.com`, `thingiverse.com`, `web.archive.org`). Header spoofing alone often isn't enough: many blocks key on the TLS/JA3 fingerprint, not the UA string. `polyfetch-scrape` is the next rung — browser-shape headers in the cheap tier, real TLS impersonation in the middle tier, and headless Chromium with anti-detection patches as the fallback — escalating only when a tier is actually blocked.

## References

- [Public API reference](docs/api-reference.md) — full signatures for `fetch`, `RenderOptions`, `Response`, `RetryPolicy`, and the exception hierarchy
- [Using without installing](USING.md) — call polyfetch from another repo/agent via `uv run --directory` (env-borrow contract: invocation, JSON schema, errors, stable surface)
- [Architecture](docs/architecture.md) — fallback-chain data flow, component responsibilities, invariants
- [Roadmap](docs/roadmap.md) — delivery history + core directions ahead
- [User stories](docs/userstory.md) — who it serves and what each need maps to
- [Scraping landscape](docs/scraping-landscape.md) — tool comparison + empirical findings
- [gha-rxiv-feed-action](https://github.com/qte77/gha-rxiv-feed-action) — fetch arXiv/bioRxiv/medRxiv feeds (open APIs; polyfetch's fallback chain isn't needed for these)
- [Changelog](CHANGELOG.md) — release notes (Keep a Changelog format)
- [Codespaces — qte77/polyforge-orchestrator/docs/codespaces.md](https://github.com/qte77/polyforge-orchestrator/blob/main/docs/codespaces.md) — canonical cross-qte77 reference for Codespaces auth, token precedence, GPG signing, devcontainer lifecycle

## License

Licensed under the [Apache-2.0](LICENSE) license (SPDX: `Apache-2.0`); see also [NOTICE](NOTICE).
