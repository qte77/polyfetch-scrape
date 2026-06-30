# 001 — Wave-1 quick wins (P0 issues)

> Status: §1 (#66) + §2 (#26) implemented on `feat/wave1-quick-wins`. §3 (#27+#28) and §4 (#47/#70)
> are GATED behind a checkpoint — not started. See the handoff: `docs/handoffs/001-wave1-quick-wins.md`.

## Context

The open-issue triage ranked four P0 items as the highest-ROI starting batch: one real bug, one
cheap evasion win, typed terminal-status errors, and fallback-tier control. All grounded in verified
current code. Right-sized into a **non-breaking quick-wins batch now** (#66, #26, close #14) with the
**breaking / feature work gated** (#27+#28, #47/#70) pending explicit sign-off.

## Execution order & checkpoints

- **Now:** §0 (this doc + handoff, close #14) → §1 (#66) → §2 (#26). Branch + topical commits + `make validate`.
- **CHECKPOINT — ask before §3:** same PR vs separate; KISS-minimal internals (bare error classes?
  single `tier=` vs `min_tier`/`max_tier` range?); breaking-change sign-off.
- **Gated:** §3 (#27+#28, breaking) then §4 (#47/#70).

## §1 — #66 `fetch --show-body` writes raw bytes (BUG)

Root cause: `cli.py` did `typer.echo(resp.body.decode("utf-8","replace"))` on `bytes` — emits 0 bytes
on non-UTF-8/non-TTY stdout and mangles binary. Fix: `sys.stdout.buffer.write(resp.body)` + flush;
remove the `# pragma: no cover`. Regression test in `tests/test_cli.py`: non-UTF-8 body, assert
`result.stdout_bytes == body`. CHANGELOG `### Fixed`.

## §2 — #26 httpx `Accept` + `Accept-Language` defaults

Extend the default-header helper in `_backends/httpx_backend.py` with two more case-insensitive
guards (caller value wins). httpx tier only. Tests mirror the existing default-UA tests. CHANGELOG `### Changed`.

## §3 — #27 + #28 typed terminal-status errors, wired (BREAKING) — GATED

Add `AuthRequired` (401/407) + `GoneError` (404/410) subclasses of `FetchError`; raise them in each
backend's `_attempt_once` (DRY helper in `_backends/__init__.py`) so terminal 4xx **raise** instead of
returning a `Response`. Export via `__init__`/`client` `__all__`. Update `test_fetch_does_not_retry_on_404`
→ `pytest.raises(GoneError)`. New `tests/test_errors.py`. CHANGELOG `### Added` + `### Changed`; README
Public API. 451→`LegalBlock` is #30, out of scope. Internal shape (bare vs `.status`-carrying) decided at checkpoint.

## §4 — #47 + #70 tier control (Added) — GATED, after §3

Add tier-selection control to `client.fetch()` (API shape — single `tier=` pin vs `min_tier`/`max_tier`
range — decided at checkpoint) + `--min-tier`/`--max-tier` (or `--tier`) CLI flags. Validate that
`wait_for_selector` without the playwright tier raises (fixes #70's silent no-op). Tests via the
`monkeypatch.setattr(".../attempt", fake)` + call-counter pattern. README Public API + Fallback Chain; CHANGELOG `### Added`.

## Documentation coverage

- CHANGELOG: Fixed (#66), Changed (#26; #27/#28 terminal-4xx raise), Added (#27 types; #47/#70 tier params).
- README: Public API (fetch signature + exception list) + Fallback Chain note — for §3/§4.
- CONTRIBUTING: no change (no new `make` recipe; switches via `--help`). roadmap/architecture/userstory: none/N-A.
- No new env vars; no new URL. New CLI switches documented via typer `--help` + README.

## Git / PR

Branch `feat/wave1-quick-wins`; topical commits per concern; `make validate` green; squash PR gated on
CI green (markdownlint + lychee); squash-merge; delete branch. Breaking note in PR body when §3 lands.
