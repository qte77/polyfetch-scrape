# 002 — 0.3.x status-code milestone + safe quick wins (two PRs)

> Status: **shipped** — PR A ([#81](https://github.com/qte77/polyfetch-scrape/pull/81)) + PR B ([#82](https://github.com/qte77/polyfetch-scrape/pull/82)), both merged 2026-07-02. Only #31 (redirects) remains in 0.3.x. Handoff: `docs/handoffs/002-status-code-milestone-and-quickwins.md`.

## Context

Finish the highest-ROI open work and complete the 0.3.x roadmap milestone (which gates the v0.4.0
release). Two PRs, in order: **PR A** non-breaking quick wins, then **PR B** the breaking status-code
unit. Strict TDD (tests first → red → green) for module changes; docs-only items need no tests.
Bare error subclasses (matching `FingerprintBlock`); preserve the #29 Retry-After, #44 logging, and
`tier=` behavior already on `main`.

**Confirmed decisions:** terminal-status raise wired in **all 3 backends** (consistent typed errors
regardless of serving tier); #48 ships **both** `etag` + `last_modified` validators; `#48` on-disk
cache is a **non-goal** (skip).

## PR A — safe quick wins (non-breaking): #35, #48, #42

- **#48 conditional requests (module → TDD):** `client.py` `fetch()` gains
  `etag: str | None = None, last_modified: str | None = None`; a small helper
  `_with_conditional_headers(headers, etag, last_modified)` injects `If-None-Match` /
  `If-Modified-Since` when the caller omits them (keeps `fetch()` flat, complexipy < 15). 304 already
  passes through (not retried/fingerprint/terminal) → caller reads `resp.status == 304` + `resp.headers`.
  Tests first (`tests/test_client.py`, respx): validator headers sent; 304 → `Response(status=304)`;
  caller-supplied header wins.
- **#35 README "When to reach for this" (docs-only):** add the section (issue ships exact "safer
  wording") between intro and Quick Start. Site names are plain text (not links) → lychee unaffected.
- **#42 defusedxml rule (docs-only):** add to `AGENT_LEARNINGS.md` (Learned Patterns) + cross-ref the
  `AGENTS.md` "Network caution" bullet. No code change (`sources/arxiv.py` already uses `defusedxml`).
- **Docs:** CHANGELOG `### Added` (#48) + docs note (#35). **Closes #35, #48, #42.**

## PR B — status-code semantics (BREAKING): #27, #28, #30, #34

- **#27 typed errors (`errors.py`):** bare `AuthRequired` (401/407), `GoneError` (404/410),
  `LegalBlock` (451) subclasses of `FetchError`.
- **#28 + #30 raise on terminal status (backends → TDD):** shared raiser in `_backends/__init__.py`:
  `_TERMINAL = {401:AuthRequired, 407:AuthRequired, 404:GoneError, 410:GoneError, 451:LegalBlock}` +
  `raise_for_terminal_status(status, url)`. Call it in **all three** `_attempt_once` (httpx, curl,
  playwright) before building the success `Response`. Terminal statuses raise (not `FingerprintBlock`)
  → propagate past the orchestrator, no retry/escalation; 451 never reaches fingerprint tiers.
  - Behavioral change: `test_fetch_does_not_retry_on_404` → `pytest.raises(GoneError)`.
  - Tests first: new `tests/test_errors.py`; per-backend 401→AuthRequired, 404→GoneError, 451→LegalBlock.
  - Exports: the three types → `__init__.py` `__all__` (+ `client` re-export).
- **#34 status-code taxonomy doc (docs-only):** add the table (issue ships it) to
  `docs/scraping-landscape.md` near "Empirical findings"; map each code to its implemented type;
  301/308 row notes "see #31".
- **Roadmap refresh:** `docs/roadmap.md` 0.3.x — mark #26/#27/#28/#29/#30/#34 done; only #31 remains.
- **Docs:** CHANGELOG `### Added` (types) + `### Changed` (terminal 4xx/451 raise — BREAKING) + README
  Public API exception list. **Closes #27, #28, #30, #34 — and #75** (its §3 + §4 both done).

## Sequencing / Git

Two branches, two squash PRs; PR A (non-breaking) first, then PR B (breaking). TDD red→green;
`make validate` green per PR; CI green; squash-merge; delete branches. After PR B, 0.3.x is complete
→ ready for the **v0.4.0 release** (separate step). gh calls need `env -u GH_TOKEN -u GITHUB_TOKEN`.

## Documentation coverage

CHANGELOG (#48 Added, #35 docs, #27 Added, #28/#30 Changed-BREAKING); README (#35 section + Public
API list). No new CLI switches / env vars / URLs (`etag`/`last_modified` are library kwargs).
roadmap + scraping-landscape updated in PR B. CONTRIBUTING / architecture / userstory — none.

## Verification

- `make validate` green each PR (TDD tests pass; coverage ≥90).
- #48: `fetch(url, etag="x")` sends `If-None-Match`; a 304 → `Response(status=304)`.
- #27/#28/#30: `fetch(url_404)` → `GoneError`; `url_401` → `AuthRequired`; `url_451` → `LegalBlock`
  without escalating.

## Out of scope (deferred)

`#48` on-disk cache (non-goal); #31 redirects (heavier, stays in 0.3.x); #80 min/max tier range;
`#46`/#49/#67/#68/#71/#72/#32/#33/#36/#39/#41/#55/#59/#60.
