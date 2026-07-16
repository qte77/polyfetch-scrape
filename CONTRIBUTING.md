<!-- markdownlint-disable MD024 -->
# Contributing to polyfetch-scrape

**This document contains technical development workflows, coding standards, and command reference shared by both human developers and AI coding agents.** For AI agent behavioural rules, see [`AGENTS.md`](AGENTS.md). For project overview and navigation, see [`README.md`](README.md).

## Instant Commands

**Setup:**

- `make setup_dev` — sync dev deps via `uv`
- `make setup_browsers` — one-off; install Patchright Chromium (~300 MB; required only for the patchright tier)
- `make doctor` — check the browser-tier Chromium is installed and install it if missing (idempotent; handy when borrowing polyfetch's venv, where the Chromium cache can get wiped)

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
| `make setup_browsers` | Install Patchright Chromium | Required only for patchright tier; ~300 MB |
| `make doctor` | Check the browser-tier Chromium is installed; install if missing | Wraps `polyfetch doctor --fix`; idempotent; for borrowed-venv consumers |
| `make lint_src` | Format + lint `src/` with ruff | |
| `make lint_tests` | Format + lint `tests/` with ruff | |
| `make type_check` | Static type check with pyright (strict) | |
| `make complexity` | Cognitive complexity with complexipy | Default threshold 15 |
| `make test` | Run unit tests (verbose; e2e skipped) | |
| `make test_e2e` | Run e2e tests against real network | Opt-in; requires `make setup_browsers` |
| `make test_coverage` | Unit tests with coverage threshold | Threshold 90 % |
| `make validate` | Full pre-commit pipeline | lint + types + complexity + cov |
| `make ci` | Check-only CI pipeline (no mutation) | Same gates as `validate`, non-mutating; run by `.github/workflows/test.yml` |
| `make quick_validate` | Fast inner-loop validation | lint + types only |
| `make changelog_new` | Add + stage a scriv changelog fragment for this PR | Edit the generated `changelog.d/*.md` |
| `make changelog_preview` | Preview the assembled release entry | Reads `changelog.d/` fragments |
| `make changelog_release VERSION=X.Y.Z` | Collect fragments into `CHANGELOG.md` | Run by the release pipeline; manual for a local cut |
| `make probe URL=... [JSON=1] [BROWSER=chrome\|firefox] [MAX_ATTEMPTS=N]` | Probe a single URL via CLI | Wraps `polyfetch fetch` |
| `make probe_bulk FILE=... [WORKERS=N] [TEXT=1] [MAX_ATTEMPTS=N]` | Probe URLs from a file (skips `#` comments + blank lines) | Wraps `polyfetch bulk`; e.g. `FILE=examples/fallback-tier-targets.txt` |
| `make demo_tiers` | Demo all 3 fallback tiers: httpx/curl_cffi JA3 diff + Patchright render+screenshot | Wraps `examples/fallback_tiers_demo.py`; needs `make setup_browsers` |
| `make discover URL=... [JSON=1]` | Discover a site's structured entrypoints (sitemaps/feeds/llms.txt/JSON-LD) | Wraps `polyfetch discover` |
| `make hunt [URL=...] [SEEDS=file] [JSON=1] [WELLKNOWN=1]` | Scan fetched pages for notable artifacts (`easter_hunt` contrib) | Default seeds: `examples/easter-hunt-seeds.txt` |
| `make render [URL=... ] [OUT=dir] [DEVICE=name] [COLOR_SCHEME=light\|dark] [VIDEO_OUT=dir]` | Render a dynamic page + screenshot via Patchright; also demos device/color-scheme emulation + video recording | Wraps `examples/render_screenshot.py`; needs `make setup_browsers` |
| `make help` | Show all recipes | |

Direct CLI (when `make` doesn't fit): `uv run polyfetch fetch URL [options]` and `uv run polyfetch bulk FILE [options]`. Run `uv run polyfetch --help` for the full surface.

Consuming polyfetch from **another** project or an agent *without installing it* (env-borrow via `uv run --directory`, no venv poison): see [`USING.md`](USING.md).

## Tooling discipline

- **Always go through `make` or `uv run`.** Never invoke `pip`, bare `pytest`, bare `ruff`, bare `pyright`, or bare `polyfetch`. The single exception is `pip install uv -q` inside `setup_uv` — bootstrap-only.
- **`make validate` must pass green before any commit.** No `--no-verify`, no skipping hooks.
- **Tests must not hit the network in `make test`.** Real-network checks live behind the opt-in `e2e` pytest marker.

## Pre-commit checklist

1. `make validate` — must exit 0
2. Add a scriv changelog fragment (`make changelog_new`) if your change is non-trivial (see below)
3. Update `README.md` if any user-facing surface changed (install, CLI, fallback behaviour, public API)

## CHANGELOG requirements

All non-trivial changes add a [scriv](https://scriv.readthedocs.io/) **fragment** under `changelog.d/` — **not** a manual `CHANGELOG.md` edit. Fragments are collected into a dated `## [X.Y.Z]` section by the release pipeline (see [Commit and PR conventions](#commit-and-pr-conventions)).

1. `make changelog_new` — creates + stages `changelog.d/<timestamp>_<branch>.md`.
2. Edit it: uncomment the relevant `### Added / Changed / Deprecated / Removed / Fixed / Security` heading (only those that apply) and write the entry in [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) style. `make changelog_preview` shows the assembled result.

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
- **Releases** are automated — see [README → Versioning](README.md#versioning): run the **Bump version** workflow (it bumps the version files and runs `scriv collect` to fold `changelog.d/` fragments into a dated `CHANGELOG.md` section), then merge the `chore(release)` PR **with a PAT** so **Tag and Release** fires.

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
