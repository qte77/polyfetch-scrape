<!-- markdownlint-disable MD024 no-duplicate-heading -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

**Types of changes**: Added, Changed, Deprecated, Removed, Fixed, Security.

## [Unreleased]

## [0.3.1] - 2026-04-26

### Added

- `polyfetch` CLI (typer-based): `polyfetch fetch URL`, `polyfetch bulk FILE`, `polyfetch --version`. `fetch` defaults to human text; `--json` opts in. `bulk` defaults to JSON-lines; supports `--workers N` for `ThreadPoolExecutor` concurrency. Bulk continues on error and exits 1 if any URL failed.
- `make probe URL=...` recipe wrapping the CLI.
- `[project.scripts]` entrypoint in `pyproject.toml`; `typer` promoted from transitive to explicit runtime dep.

### Fixed

- `pyproject.toml` `license` field now uses the SPDX expression string per PEP 639 instead of the deprecated `{ text = "Apache-2.0" }` table form. Schema validators were rejecting the inline-table.

## [0.3.0] - 2026-04-26

### Added

- Patchright (Apache-2.0 CDP-leak-patched Playwright fork) as the third fallback tier in `_backends/playwright_backend.py`. Triggered when both httpx and curl_cffi raise `FingerprintBlock`. Headless Chromium with `wait_until="domcontentloaded"`.
- `wait_for_selector: str | None` kwarg on `fetch()`; threaded only into the playwright tier.
- `make setup_browsers` recipe (`uv run patchright install chromium`); separate from `setup_dev` because the binary is ~300 MB.
- `docs/scraping-landscape.md` → "Empirical findings — polyfetch-scrape probes" subsection with first-party citations from curl_cffi and Patchright READMEs.

### Changed

- `Response.backend` literal widened to `"httpx" | "curl_cffi" | "playwright"`.
- `client.fetch()` becomes a three-tier orchestrator: httpx → curl_cffi → playwright.

### Notes

- Hardened Cloudflare targets (g2.com tier) remain blocked in headless CI; Patchright's own README requires `launch_persistent_context(channel="chrome", headless=False)` for those, which CI doesn't provide. Documented as `test_g2_remains_blocked_in_headless_ci` xfail with the cited reason.

## [0.2.0] - 2026-04-26

### Added

- `_backends/curl_backend.py` — second fallback tier with Chrome TLS impersonation via `curl_cffi`.
- Internal `FingerprintBlock` sentinel in `_backends/__init__.py`: raised by httpx tier on persistent 403 / TLS error so the orchestrator falls through to curl_cffi.
- `browser: "chrome" | "firefox"` kwarg on `fetch()` for impersonation profile selection.
- E2e proof: `test_cloudflare_fronted_target_succeeds_via_curl_cffi` (against `nowsecure.nl`, the curl_cffi project's canonical anti-bot demo target).

### Changed

- httpx logic refactored into `_backends/httpx_backend.py`; `client.fetch()` becomes a thin orchestrator over the backend modules.
- `FetchError` moved from `client.py` to `errors.py` to break a `client` ↔ `_backends` import cycle.
- `Response.backend` literal widened to `"httpx" | "curl_cffi"`.

## [0.1.0] - 2026-04-26

### Added

- `src/polyfetch_scrape/client.py` — sync `fetch(url, *, method, headers, timeout, retry) -> Response` over `httpx.Client`. Retries `{429, 500, 502, 503, 504}` and `httpx.TransportError`; raises `FetchError` after exhausting `RetryPolicy.max_attempts`.
- `src/polyfetch_scrape/response.py` — frozen `Response` dataclass: `url`, `status`, `headers`, `body`, `content_type`, `backend`.
- `src/polyfetch_scrape/retry.py` — `RetryPolicy` + `should_retry()` predicate. Defaults: 3 attempts, 0.2 s initial backoff, ×2 factor.
- `Makefile` mirroring qte77/Agents-eval recipes (`setup_uv`, `setup_dev`, `lint_src`, `lint_tests`, `type_check`, `complexity`, `test`, `test_coverage`, `validate`, `quick_validate`); all wrap `uv run` (uv-only).
- `pyproject.toml` — `pytest filterwarnings = ["error"]`, branch coverage with `fail_under = 90`, pyright `typeCheckingMode = "strict"`.
- Opt-in `e2e` pytest marker + `make test_e2e` recipe (httpbin / arxiv smoke tests, no network in default `make test`).

[Unreleased]: https://github.com/qte77/polyfetch-scrape/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/qte77/polyfetch-scrape/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qte77/polyfetch-scrape/releases/tag/v0.1.0
