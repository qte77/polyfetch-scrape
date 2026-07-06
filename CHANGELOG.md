<!-- markdownlint-disable MD024 no-duplicate-heading -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

**Types of changes**: Added, Changed, Deprecated, Removed, Fixed, Security.

## [Unreleased]

### Added

- `polyfetch fetch` conditional-GET flags — `--etag` and `--if-modified-since` send `If-None-Match` / `If-Modified-Since` so a cached URL returns `304 Not Modified` on a match (bandwidth-cheap re-fetches). Exposes the existing `fetch(..., etag=, last_modified=)` kwargs on the CLI; a caller-supplied header of the same name still wins. Closes #85.
- CI: `bump-version` + `tag-release` GitHub Actions workflows — automate the two-step release pipeline (`bump-my-version` → `chore(release)` PR → tag + GitHub Release from the CHANGELOG section), matching the qte77 sibling convention. `[tool.bumpversion]` in `pyproject.toml` drives the file/CHANGELOG rewrites (incl. the `uv.lock` self-ref). See README "Versioning".
- `USING.md` — machine-facing "use without installing" contract for consuming polyfetch from another project or agent via `uv run --directory` (env-borrow, no venv poison): canonical invocation, `--json` output schema, error/exit-code contract, and the stable public surface. Discoverable from README (role nav + References) and CONTRIBUTING. Folds in #41.
- CI: `.github/workflows/test.yml` + a check-only `make ci` recipe — runs ruff (check-only), pyright, complexipy, and pytest (coverage ≥ 90, e2e skipped) on every push/PR to `main`. Python tests/types/lint previously ran only locally via `make validate`; they now gate PRs. `make ci` is the non-mutating counterpart of `make validate` (uses `ruff format --check` / `ruff check` instead of the `--fix` formatters). Closes #98.
- `polyfetch fetch` render flags for the playwright tier — `--wait-until`, `--wait-for-selector`, `--wait-for-function`, and `--screenshot viewport|<css>` + `--screenshot-out <path>` (writes the PNG). Exposes the existing `RenderOptions` surface on the CLI so env-borrow/agent consumers can render + screenshot without an in-clone script (`actions` stay Python-only). Base64 screenshot inside `--json` deferred to #105. Closes #94.
- `RenderAction` + `RenderOptions(actions=...)` — scripted playwright steps (`click`/`click_text`/`fill`/`wait_for_selector`/`wait_ms`) run **in order, before** the waits/capture, so callers can drive a page (toggle a control, fill a field) before screenshotting. Exported from the package root alongside `RenderOptions`; library-only (not CLI-expressible — structured, not flag-shaped). Closes #71.

### Changed

- `polyfetch fetch`/`bulk` now emit **structured JSON errors** under `--json`: both share the schema `{url, error_type, status, message}` (`fetch` prints it to stdout, honoring `--json` on failure; every failed `bulk` line matches). `error_type` is the exception class (`GoneError`/`AuthRequired`/`LegalBlock`/`FetchError`) and `status` the terminal HTTP code (or `null`); terminal exceptions now carry `.status`. **Breaking for `bulk` JSON consumers:** replaces the old `{"error": "GoneError: …", "backend": null}` line shape. Closes #101.

### Fixed

- Playwright tier now **retries retryable 5xx statuses** (`{429,500,502,503,504}`) and honors `Retry-After`, matching the httpx/curl_cffi tiers. Previously a 5xx response was wrapped and returned as success instead of being retried; a persistent 5xx now raises `FetchError` after `max_attempts`. Closes #84.

## [0.5.0] - 2026-07-04

### Added

- `RenderOptions` + `fetch(url, *, render=RenderOptions(...))` — grouped playwright-tier controls: `wait_until` (`"networkidle"` lets XHR settle), `wait_for_selector`, `wait_for_function` (JS predicate — captures client-hydrated values), and `screenshot` (`"viewport"` or a CSS selector → PNG bytes on `Response.screenshot`; `full_page` unsupported — Chromium writes 0 bytes on tall pages). Ignored by the httpx/curl_cffi tiers. `wait_for_selector` stays as a top-level `fetch()` convenience that seeds `render`. Closes #67, #68.
- `Response.permanent_redirect_to: str | None` — set to the `Location` target on a permanent redirect (301/308) so callers can update stored URLs; `None` for temporary redirects (302/303/307) and non-redirects. Populated by all three backends. Closes #31.
- `docs/architecture.md` + `docs/userstory.md` — fallback-chain data flow / component responsibilities / invariants, and a user-story→coverage map (matches the qte77 sibling-repo doc convention); linked from README + CONTRIBUTING.

### Removed

- **BREAKING:** the arXiv source wrapper (`polyfetch_scrape.sources.arxiv`, the `sources/` namespace) and the `polyfetch arxiv get` CLI subcommand; dropped the now-unused `defusedxml` dependency. Domain API wrappers move to downstream packages that consume `fetch()` — see #89.

## [0.4.0] - 2026-07-02

### Added

- Typed terminal-status errors `AuthRequired` (401/407), `GoneError` (404/410), and `LegalBlock` (451) — all `FetchError` subclasses, exported from the package root alongside `FetchError`. A shared `raise_for_terminal_status()` in `_backends/` maps each status to its type. Closes #27.
- `fetch(url, *, etag=..., last_modified=...)` — conditional requests for polling callers: sets `If-None-Match` / `If-Modified-Since` so an unchanged resource returns `Response(status=304)` (empty body) and the caller skips re-downloading/re-parsing. Caller-supplied conditional headers (any case) win; on-disk validator cache out of scope. Closes #48.
- `README.md` "When to reach for this" section framing polyfetch-scrape against Claude Code's WebFetch ceiling (no header control, default UA 403s on hardened sites, no TLS-fingerprint control, no JS rendering). Closes #35.
- `fetch(url, *, tier="httpx"|"curl_cffi"|"playwright")` and `polyfetch fetch --tier ...` — pin a single backend and skip the fallback chain: force the browser tier for known-JS pages (#70) or fail fast on the cheap httpx tier without escalating to the slow browser tier (#47). The pinned backend's error propagates directly (no escalation); `wait_for_selector` only applies when the playwright tier runs. Closes #47, #70.
- Tier-escalation logging: `fetch()` emits an `INFO` record on the `polyfetch_scrape` logger each time it escalates a tier (httpx → curl_cffi → playwright). The package attaches a `NullHandler`, so it stays silent until the application configures logging — observability for "why did this request reach the browser tier?". Closes #44.
- `easter_hunt` contrib module (`src/polyfetch_scrape/contrib/easter_hunt/`) — opt-in page-artifact scanner built on the public `fetch()`. Three pure detectors (`html_comments` recruiting/novelty comments, `weird_headers` curated header table, `wellknown_present` with a soft-404 body sniff), a `hunt()` orchestrator, a `polyfetch easter-hunt scan` CLI subcommand (`--seeds-file`, `--include-wellknown`, `--json`), and a `make hunt` recipe + `examples/easter-hunt-seeds.txt`. Contrib is an unsupported extra: core never imports it and removing the directory leaves the core CLI functional.
- **Stage 0.4.0 part 1: arXiv source wrapper** (`polyfetch_scrape.sources.arxiv`):
  - `ArxivPaper` frozen dataclass: `arxiv_id`, `title`, `authors`, `abstract`, `categories`, `pdf_url`, `abs_url`, `published_at`, `updated_at`.
  - `get(arxiv_id, *, timeout=30.0) -> ArxivPaper` calls `fetch()` against the arXiv export API and parses Atom XML via `defusedxml.ElementTree` (mitigates Bandit B314).
  - `ArxivError(FetchError)`, `ArxivNotFoundError`, `ArxivParseError` exception types.
  - CLI: `polyfetch arxiv get ID [--json]`.
  - E2e: `test_arxiv_source_get_real_api` against real arXiv API.
- New top-level `sources/` namespace (vs private `_backends/`); first source.
- `.devcontainer/devcontainer.json` — Codespaces config mirroring qte77/polyforge-orchestrator; `containerEnv` maps `GH_PAT` user-secret to `GH_TOKEN`; `postCreateCommand: gh auth setup-git` so `git push` also honours `$GH_PAT`.
- `CONTRIBUTING.md` — three-file separation (README orientation / CONTRIBUTING commands+standards / AGENTS.md AI-rules) per qte77/Agents-eval.
- `make probe_bulk FILE=urls.txt [WORKERS=N] [TEXT=1]`; `make probe` gains `BROWSER=`, `MAX_ATTEMPTS=` overrides.
- `polyfetch_scrape.utils.http_ua` — generalized port of `qte77/scrape-stock-kpi/src/utils/http_ua.py` (no pydantic-settings dep): `USER_AGENTS` tuple of 5 desktop browser UAs (refresh quarterly from useragents.me/), `STABLE_USER_AGENT = USER_AGENTS[0]` for endpoints that profile per-UA over time, `pick_user_agent(rng=None)` for rotation with optional seeded RNG. The sibling repo's `require_https()` guard is intentionally not ported (incompatible with this project's "fetch any URL" contract).
- `polyfetch fetch --show-body` — prints the raw response body instead of the summary; handy for verifying the outbound `User-Agent` against a header-echo endpoint (e.g. `polyfetch fetch https://httpbin.org/user-agent --show-body`; also `postman-echo.com/headers` or `ifconfig.me/ua`). Takes precedence over `--json`.
- `examples/fallback-tier-targets.txt` + `examples/fallback_tiers_demo.py` (`make demo_tiers`) — the hardest ToS-safe target per fallback tier, and a runnable demo that drives each backend directly: httpx-vs-curl_cffi TLS/JA3 fingerprint diff, plus a Patchright JS render with a screenshot (`examples/screenshots/`, git-ignored). `lychee.toml` excludes the two anti-bot challenge URLs that 403 every tier by design.
- `examples/render_screenshot.py` (`make render [URL=... ] [OUT=dir]`) — minimal direct-drive Patchright/Chromium renderer for dynamic (JS) pages: waits for `networkidle`, then saves a full-page and a viewport PNG to `--out-dir` (default `examples/screenshots/`, git-ignored). Defaults to `quotes.toscrape.com/js` so `make render` is a bare demo. A stop-gap until first-class screenshots land in the toolkit (#68); richer knobs (wait strategies, `full_page`→clip fallback, console capture) are tracked against #67/#68/#72.

### Changed

- **BREAKING:** terminal HTTP statuses now **raise** a typed error instead of returning a `Response`. 401/407 → `AuthRequired`, 404/410 → `GoneError`, 451 → `LegalBlock`, raised on the first attempt in all three backends (httpx, curl_cffi, playwright) with no retry and no tier escalation — 451 in particular never reaches the fingerprint tiers (RFC 7725). Callers that previously inspected `resp.status == 404` must now catch `GoneError` (or its base `FetchError`). The CLI reflects this too: `polyfetch fetch` now exits 1 (e.g. `FetchError: terminal HTTP 404: ...`) on these statuses instead of printing a status summary, and `polyfetch bulk` counts them as failures. Closes #28, #30, #34, #75.
- Retry/backoff now honors a server `Retry-After` header on retryable responses (429/503/5xx): `_backends/{httpx,curl}_backend` parse `Retry-After` (delta-seconds or HTTP-date via `retry.parse_retry_after`) and wait that long — capped at `RETRY_AFTER_CAP_S` (60s) by `retry.next_delay` to avoid a pathological hang — instead of the exponential backoff, falling back to exponential when the header is absent/unparseable. Prevents the fixed backoff from retrying before the server's cooldown elapses (which can escalate a 429 to a hard block). Closes #29.
- `polyfetch bulk FILE` (and `make probe_bulk`) now skip blank lines and `#`-prefixed comments when reading the URL file, matching `easter-hunt scan --seeds-file`. `examples/fallback-tier-targets.txt` is now runnable as a whole: `make probe_bulk FILE=examples/fallback-tier-targets.txt`.
- `README.md` + `CONTRIBUTING.md` — surface the demo recipes: README Fallback-Chain section now points to `make demo_tiers` and `examples/fallback-tier-targets.txt` (ToS-safe targets per tier difficulty, runnable via `make probe_bulk`); CONTRIBUTING command reference gains `make demo_tiers` and `make hunt` rows. Closes #62.
- `make probe_bulk` now forwards `MAX_ATTEMPTS=N` to `polyfetch bulk` (matching `make probe`), so the tier ladder can fail fast on the Ceiling 403s.
- Example screenshots (`examples/screenshots/*.png`, including the `demo_tiers` sample) are now git-ignored and no longer tracked — regenerable via `make demo_tiers` / `make render`; stops binary churn on re-runs.
- `_backends/httpx_backend.py` — now also injects browser-default `Accept` and `Accept-Language` headers when the caller omits them (helper renamed `_with_default_ua` → `_with_default_headers`). httpx's `Accept: */*` and absent `Accept-Language` were additional bot tells on the cheap httpx tier; caller-supplied values (any case) still win. Closes #26.
- `_backends/httpx_backend.py` — outbound `User-Agent` now defaults to `STABLE_USER_AGENT` (Chrome-on-Windows desktop) when the caller doesn't supply one; httpx's `python-httpx/X.Y.Z` default was an immediate bot tell on hardened endpoints, defeating the cheap httpx tier before TLS-fingerprint fallback would even matter. Caller-supplied `User-Agent` (any case) wins. Closes #16.
- `pyproject.toml` — ruff `[tool.ruff.lint] select` graduated per py-harden-ruff §1: adds baseline `I, N, W, UP` and near-free quality + security `B, S, SIM, RUF, PT, PGH` (deferred for follow-ups: `ANN`, `D`, `TC`, `TRY`, `C90`). `tests/**` ignores `S101` (asserts) and `S311` (seeded `random.Random()` for determinism, not crypto). Closes #21.
- `README.md` Development section delegates to `CONTRIBUTING.md` (single source of truth).
- `README.md` References now points at `qte77/polyforge-orchestrator/docs/codespaces.md` as the canonical cross-qte77 home for Codespaces auth/git documentation.
- `AGENTS.md` cross-refs `CONTRIBUTING.md` and mandates `make` recipes + `make validate` before reporting task complete.
- `Makefile` adopts qte77/Agents-eval `# MARK:` section-marker convention (SETUP / QUALITY / APP / HELP) for cross-project muscle memory; `help` recipe now prints recipes grouped under bold section headings via the same awk pattern.

### Removed

- `docs/codespaces-auth.md` and `docs/codespaces-git-defaults.md` — content merged into `qte77/polyforge-orchestrator/docs/codespaces.md` as the canonical cross-qte77 home (single source of truth across qte77 ecosystem). README links now point there.
- `docs/scraping-landscape.md` — the full scraping/crawling/extraction tool catalog; reduced to a pointer stub at the `ai-agents-research` SSOT (`docs/non-cc/web-scraping-extraction-landscape.md`, moved 2026-06-16 via `ai-agents-research#248`). Retains only this repo's own `httpx → curl_cffi → Patchright` fallback-chain probe findings. Closes #52.

### Fixed

- `polyfetch fetch --show-body` now writes the raw response **bytes** via `sys.stdout.buffer` instead of decoding to text first. The old `typer.echo(body.decode("utf-8", "replace"))` emitted nothing when stdout was redirected/piped under a non-UTF-8 locale and mangled binary bodies; the byte-level write preserves the exact server response on every stdout type. Closes #66.
- `Makefile` `probe` recipe no longer leaks shell-env vars (e.g. devcontainer-set `BROWSER=...`); flag forwarding now uses `$(origin VAR)` to gate on `command line`/`file` only.
- `CONTRIBUTING.md` — replaced YAML frontmatter with a proper `# Contributing to polyfetch-scrape` H1 so `markdownlint-cli2` MD041 / MD022 / MD003 all pass (frontmatter wasn't rendered by GitHub anyway).
- `lychee.toml` — new local lychee config narrowly excluding (a) `compare/` + `releases/tag/` URLs to v0.1.0..v0.3.1 that CHANGELOG references but were never pushed as tags, (b) `www.epo.org` which intermittently returns HTTP/2 protocol errors. Both block every PR on `main` until addressed; the real fix for (a) is to push the tags retroactively.

### Security

- `sources/arxiv.py` parses XML via `defusedxml.ElementTree.fromstring` instead of stdlib `xml.etree.ElementTree.fromstring` to mitigate XML attacks (billion-laughs, external entity expansion). Stdlib `xml.etree.ElementTree.fromstring` on untrusted XML is Bandit B314.
- `easter_hunt.hunt()` enforces a literal-IP SSRF guard before every fetch: a seed whose host is a private, loopback, link-local, unspecified, reserved, or multicast IP raises `ValueError` (surfaced as exit 2 by the CLI) before any network call. Literal-IP only — DNS-based SSRF and obfuscated IP encodings (decimal/hex/octal) are documented as out of scope for v0.1.

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

[Unreleased]: https://github.com/qte77/polyfetch-scrape/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/qte77/polyfetch-scrape/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qte77/polyfetch-scrape/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/qte77/polyfetch-scrape/releases/tag/v0.1.0
