# Handoff — 001 Wave-1 quick wins

**Branch:** `feat/wave1-quick-wins` · **Plan:** `docs/plans/001-wave1-quick-wins.md`

## Goal

Ship the non-breaking P0 quick wins now; gate the breaking/feature P0 work behind a checkpoint.

## Status

| § | Item | State |
|---|---|---|
| §0 | close #14 (stale scratch issue) | done |
| §1 | #66 `--show-body` raw-bytes fix + regression test | done |
| §2 | #26 httpx `Accept`/`Accept-Language` defaults + tests | done |
| §3 | #27+#28 typed terminal-status errors, wired (**breaking**) | **GATED — not started** |
| §4 | #47+#70 tier control (force/cap fallback) | **GATED — after §3** |

`make validate` green on §1+§2. PR held until the checkpoint decisions below.

## Decisions still open (the checkpoint, before §3)

1. **Same PR or separate** — fold §3/§4 into this branch, or new branches/PRs (the breaking §3 may
   warrant isolation).
2. **#27 error shape** — bare subclasses (match `FingerprintBlock`) vs `.status`-carrying base.
3. **Tier API** — single `tier=` pin (KISS) vs `min_tier`/`max_tier` range.
4. **Breaking-change sign-off** — §3 makes 401/404/407/410 raise instead of returning a `Response`
   (breaks `if resp.status == 404`).

## How to resume §3

`errors.py` + a DRY `raise_for_terminal_status()` in `_backends/__init__.py`, called in all three
backends' `_attempt_once`; export the new types; update `test_fetch_does_not_retry_on_404`; add
`tests/test_errors.py`; CHANGELOG `### Added`+`### Changed`; README Public API. Then §4 (`client.fetch`
tier control + CLI flags + `wait_for_selector` validation).

## Verify

- `make validate` exits 0.
- `polyfetch fetch https://example.com --show-body > /tmp/o.html` writes real body bytes (not 0).
- After §2: httpx requests carry `Accept` + `Accept-Language` (respx tests assert this).
