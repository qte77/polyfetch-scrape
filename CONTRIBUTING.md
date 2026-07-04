<!-- markdownlint-disable MD024 -->
# Contributing to polyfetch-scrape

**This document contains technical development workflows, coding standards, and command reference shared by both human developers and AI coding agents.** For AI agent behavioural rules, see [`AGENTS.md`](AGENTS.md). For project overview and navigation, see [`README.md`](README.md).

## Instant Commands

**Setup:**

- `make setup_dev` — sync dev deps via `uv`
- `make setup_browsers` — one-off; install Patchright Chromium (~300 MB; required only for the playwright tier)

**Inner loop:**

- `make quick_validate` — fast feedback (lint + pyright)
- `make test` — unit tests (no network)
- `make validate` — full pre-commit: lint + pyright + complexipy + coverage

**Probing (ad-hoc URL fetches via the CLI):**

- `make probe URL=https://example.com` — single URL, text output
- `make probe URL=https://example.com JSON=1` — single URL, JSON output
- `make probe_bulk FILE=urls.txt WORKERS=4` — bulk URLs (one per line), JSON-lines

**Emergency fallback** (if make recipes fail):

- `uv run ruff format . && uv run ruff check . --fix` — format + lint
- `uv run pyright src` — type check
- `uv run pytest` — tests

## Complete Command Reference

| Command | Purpose | Notes |
|---|---|---|
| `make setup_uv` | Bootstrap uv + sync frozen deps | Only target that uses `pip` (one-line bootstrap) |
| `make setup_dev` | Sync dev deps via uv | |
| `make setup_browsers` | Install Patchright Chromium | Required only for playwright tier; ~300 MB |
| `make lint_src` | Format + lint `src/` with ruff | |
| `make lint_tests` | Format + lint `tests/` with ruff | |
| `make type_check` | Static type check with pyright (strict) | |
| `make complexity` | Cognitive complexity with complexipy | Default threshold 15 |
| `make test` | Run unit tests (verbose; e2e skipped) | |
| `make test_e2e` | Run e2e tests against real network | Opt-in; requires `make setup_browsers` |
| `make test_coverage` | Unit tests with coverage threshold | Threshold 90 % |
| `make validate` | Full pre-commit pipeline | lint + types + complexity + cov |
| `make quick_validate` | Fast inner-loop validation | lint + types only |
| `make probe URL=... [JSON=1] [BROWSER=chrome\|firefox] [MAX_ATTEMPTS=N]` | Probe a single URL via CLI | Wraps `polyfetch fetch` |
| `make probe_bulk FILE=... [WORKERS=N] [TEXT=1] [MAX_ATTEMPTS=N]` | Probe URLs from a file (skips `#` comments + blank lines) | Wraps `polyfetch bulk`; e.g. `FILE=examples/fallback-tier-targets.txt` |
| `make demo_tiers` | Demo all 3 fallback tiers: httpx/curl_cffi JA3 diff + Patchright render+screenshot | Wraps `examples/fallback_tiers_demo.py`; needs `make setup_browsers` |
| `make hunt [URL=...] [SEEDS=file] [JSON=1] [WELLKNOWN=1]` | Scan fetched pages for notable artifacts (`easter_hunt` contrib) | Default seeds: `examples/easter-hunt-seeds.txt` |
| `make render [URL=... ] [OUT=dir]` | Render a dynamic page + full/viewport screenshots via Patchright | Wraps `examples/render_screenshot.py`; needs `make setup_browsers` |
| `make help` | Show all recipes | |

Direct CLI (when `make` doesn't fit): `uv run polyfetch fetch URL [options]` and `uv run polyfetch bulk FILE [options]`. Run `uv run polyfetch --help` for the full surface.

## Tooling discipline

- **Always go through `make` or `uv run`.** Never invoke `pip`, bare `pytest`, bare `ruff`, bare `pyright`, or bare `polyfetch`. The single exception is `pip install uv -q` inside `setup_uv` — bootstrap-only.
- **`make validate` must pass green before any commit.** No `--no-verify`, no skipping hooks.
- **Tests must not hit the network in `make test`.** Real-network checks live behind the opt-in `e2e` pytest marker.

## Pre-commit checklist

1. `make validate` — must exit 0
2. Update `CHANGELOG.md` `## [Unreleased]` section if your change is non-trivial (see below)
3. Update `README.md` if any user-facing surface changed (install, CLI, fallback behaviour, public API)

## CHANGELOG requirements

All non-trivial changes update `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md). Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) with sub-sections `### Added / Changed / Deprecated / Removed / Fixed / Security` (only those that apply).

**Requires a CHANGELOG entry:**

- New features or public-API changes
- Breaking changes
- Bug fixes that affect user-visible behaviour
- Documentation restructuring (this file's scope or README's surface)
- Dependency additions or version bumps that change behaviour
- Configuration / Makefile recipe changes

**Does not require a CHANGELOG entry:**

- Comment / typo fixes
- Pure code formatting
- Internal refactors with no user-visible effect
- Test-only changes

## Commit and PR conventions

- **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`, `style:`, with optional scope like `feat(cli):`).
- **Topical commits within a PR** — split by concern, not by file. Each commit should be reviewable independently.
- **Squash-merge** PRs into `main`; keep the topical-commit list in the PR description for the merge commit body.
- **Branch names**: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`, etc.

## Project conventions (quick reference)

- **Python ≥ 3.11**, src layout (`src/polyfetch_scrape/`)
- **Absolute imports only** (`from polyfetch_scrape.x import y`); never relative
- **Type hints on every signature**; modern syntax (`str | None`, `list[str]`)
- **Mocks** use `spec=RealClass` on third-party types; never mock internal functions in the same module
- **No `print()`** in `src/`; use return values or raise
- **No bare `except:`**; catch the specific exception
- **Backend modules in `_backends/`** are private; only `polyfetch_scrape.{fetch, Response, RetryPolicy, FetchError}` are public
- **Add deps via `uv add ...`** (or `uv add --group dev ...`); never edit `[project.dependencies]` by hand without re-locking via `uv sync`

For deeper architecture see [`docs/architecture.md`](docs/architecture.md); for the staged roadmap see [`docs/roadmap.md`](docs/roadmap.md). For empirical anti-bot findings (with first-party citations), see [`docs/scraping-landscape.md`](docs/scraping-landscape.md).
