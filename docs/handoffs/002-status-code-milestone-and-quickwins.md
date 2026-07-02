# Handoff — 002 status-code milestone + safe quick wins

**Plan:** `docs/plans/002-status-code-milestone-and-quickwins.md` · **Status:** shipped — PR A #81, PR B #82 (both merged 2026-07-02).

## Goal

Two PRs, in order. **PR A** = non-breaking quick wins. **PR B** = the breaking status-code unit that
completes the 0.3.x roadmap milestone (gating the v0.4.0 release).

## Confirmed decisions

- Bare error subclasses (like `FingerprintBlock`); no `.status` base.
- Terminal-status raise wired in **all 3 backends** (httpx, curl, playwright).
- #48 ships **both** `etag` + `last_modified`; on-disk cache is a **non-goal** (skip).
- Strict TDD (test first → red → green) for module changes; docs-only items need no tests.

## PR A — #35, #48, #42 (non-breaking)

| Item | Files | Test? |
|---|---|---|
| #48 conditional requests | `client.py` (`etag`/`last_modified` kwargs + `_with_conditional_headers`) | **Yes** (test_client.py: validators sent; 304→Response; caller wins) |
| #35 README pitch | `README.md` ("When to reach for this", exact text in the issue) | no (docs) |
| #42 defusedxml rule | `AGENT_LEARNINGS.md` + `AGENTS.md` cross-ref | no (docs; code already compliant) |

Docs: CHANGELOG Added (#48) + docs note (#35). Closes #35/#48/#42.

## PR B — #27/#28/#30 + #34 (BREAKING)

- `errors.py`: `AuthRequired`/`GoneError`/`LegalBlock`.
- `_backends/__init__.py`: `_TERMINAL` map + `raise_for_terminal_status(status, url)`; call in all 3
  `_attempt_once` before the success `Response`.
- 401/404/407/410/451 now **raise** (were returned as `Response`). Update
  `test_fetch_does_not_retry_on_404` → `pytest.raises(GoneError)`; new `tests/test_errors.py` +
  per-backend 401/404/451 tests.
- Exports the three types via `__init__.py` `__all__`.
- #34: taxonomy table → `docs/scraping-landscape.md`. Roadmap refresh → `docs/roadmap.md` (0.3.x: only
  #31 left). README Public API exception list; CHANGELOG Added + Changed (BREAKING).
- Closes #27/#28/#30/#34 **and #75**.

## Verify

`make validate` green per PR. `fetch(url_404)`→`GoneError`, `url_401`→`AuthRequired`,
`url_451`→`LegalBlock` (no escalation); `fetch(url, etag="x")` sends `If-None-Match`; 304→`Response(304)`.

## Resume

Start PR A: branch off `main`, write the #48 test first (red), implement, add #35/#42 docs, `make
validate`, squash PR (Closes #35 #48 #42), merge. Then PR B. After PR B → cut **v0.4.0**.
gh needs `env -u GH_TOKEN -u GITHUB_TOKEN`.
