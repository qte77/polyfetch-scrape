# 004 — Remaining high-ROI backlog (#84, #85, #39+#36, #55)

> Status: **planned, not started.** Handoff: `docs/handoffs/004-high-roi-batch.md`.
> Repo `main` — all of plan 003 merged; **Python CI is live** (`.github/workflows/test.yml` runs `make ci`
> on every push/PR). Four **independent** units — do in order. Maintainer decisions locked:
> **#84 = full parity** (retry + Retry-After); **all four units in scope** (incl. #55).

## Context

Plan 003 shipped Python CI (#98), structured JSON errors (#101), CLI render flags (#94), tier-3 scripted
actions (#71), and the USING.md env-borrow contract (#41). This is the next high-ROI × high-feasibility
batch, one CI-gated PR per unit: **#84 → #85 → (#39+#36) → #55.** Each is independent; stop after any unit.

## Source map — read these, don't re-explore

**Repo facts:** src layout `src/polyfetch_scrape/`; make-driven (never bare `pip`/`pytest`/`ruff`/`pyright`);
pyright strict with `include=["src"]` (**tests are NOT type-checked**); complexipy threshold 15; coverage
≥ 90; e2e skipped by default (`-m 'not e2e'` in `pyproject.toml`). `gh` needs `env -u GH_TOKEN -u
GITHUB_TOKEN`. **CI is live:** `make ci` = check-only `ruff format --check .` + `ruff check .` +
`pyright src` + `complexipy -q .` + `pytest --cov` (the non-mutating counterpart of `make validate`), run by
`.github/workflows/test.yml`. Local doc lint: `markdownlint-cli2 <files>` (auto-uses in-repo
`.markdownlint.jsonc`) + `lychee --config lychee.toml <files>`.

| File / path | What's there (anchors) |
|---|---|
| `src/polyfetch_scrape/_backends/httpx_backend.py` | **#84 TEMPLATE.** `_Attempt` has a `retry_after` field (l.25-30). `_attempt_once` (l.64-84): on `should_retry(status,policy)` or a 403, returns `_Attempt(None, status, None, parse_retry_after(headers.get("retry-after")))` **before** `raise_for_terminal_status` and building the Response. `attempt` loop (l.42-48) delays via `next_delay(last.retry_after, policy, idx)`. |
| `src/polyfetch_scrape/_backends/playwright_backend.py` | **#84 TARGET.** `_Attempt` dataclass = fields `response, block_status, error` (l.22-26). `attempt` loop (l.44-54) retries only when `last.response is None`; delay is **fixed** `time.sleep(policy.backoff_initial * policy.backoff_factor**idx)` (l.52). `_attempt_once` (l.65-109): calls `raise_for_terminal_status(status,url)` (l.89) then `_apply_actions`/`_apply_waits`, and **builds+returns a Response for any non-403/non-terminal status incl. 5xx** (l.92-107 — the bug). `response.all_headers()` is read at l.93. |
| `src/polyfetch_scrape/retry.py` | `RetryPolicy.retry_on_status = frozenset({429,500,502,503,504})`. `should_retry(status,policy)` (l.18). `parse_retry_after(value)` (l.22 — delta-seconds or HTTP-date → seconds or None). `next_delay(retry_after,policy,idx)` (l.43 — Retry-After wins, capped at `RETRY_AFTER_CAP_S=60`; else exponential). Reuse all three (already used by httpx/curl). |
| `src/polyfetch_scrape/client.py` | **#85 — NO client change needed.** `fetch(url, *, ..., etag=None, last_modified=None, render=None)` already has the kwargs (l.24-37); `_with_conditional_headers` (l.56-74) injects `If-None-Match`/`If-Modified-Since` (a caller-supplied header wins). The CLI just needs to pass them through. |
| `src/polyfetch_scrape/cli.py` | **#85 TARGET.** `fetch_cmd` (from l.68): add `--etag` and `--if-modified-since` `typer.Option`s (mirror the `--wait-until`/`--wait-for-function` flags added in #94, ~l.76-95) and pass `etag=…, last_modified=…` into the `fetch(...)` call (~l.93). |
| `tests/test_playwright_backend.py` | **#84 tests.** `_make_pw_chain(monkeypatch, *, goto_side_effect=…, response_status=…)` (l.18) → `(page, response)`. `test_playwright_backend_retries_on_timeout` (l.217) = **TEMPLATE** (passes a `goto_side_effect` list, asserts `page.goto.call_count == 2`). Mirror it with a 503 response then a 200. The `_no_sleep` autouse fixture (l.13) already stubs `time.sleep`. |
| `tests/test_cli.py` | **#85 tests.** `test_fetch_render_flags_build_render_options` (a `fake` fetch that records `kwargs`) = **TEMPLATE**: assert `--etag`/`--if-modified-since` reach `fetch()` as `etag`/`last_modified`. |
| `docs/scraping-landscape.md` | **#39+#36 TARGET.** Has an "Empirical findings — polyfetch-scrape probes" subsection (v0.3.0). Add the TLS/JA3-vs-UA (#39) + session UA-vs-bot-block (#36) tables there; one PR closes both. |
| `README.md` | **#55 TARGET.** Doc-structure canon — the checklist is in **issue #55's comment**: add `## What` / `## Why`; fix section order (Hero → Badges → What → How → Why → Refs → License); add a standalone `## License`; move `## Public API` full signatures out to `docs/`. |
| `USING.md` · `CHANGELOG.md` · `.markdownlint.jsonc` · `lychee.toml` | Keep in lockstep: #85 changes the CLI surface → USING.md fetch-flags line + README CLI example + `CHANGELOG.md [Unreleased]`. Doc-lint configs are already in-repo. |

---

## Unit 1 — #84 playwright 5xx retry parity (FULL: retry + Retry-After) · `fix/playwright-5xx-retry`

**Steps**

1. `playwright_backend.py`: add a 4th field `retry_after: float | None = None` to `_Attempt` (mirror httpx).
2. In `_attempt_once`, right after `raise_for_terminal_status(status, url)` (l.89) and **before** building the
   Response, insert: if `should_retry(status, policy)` → return `_Attempt(None, status, None,
   parse_retry_after(<retry-after>))`. Read the header from `response.all_headers()` (case-insensitive
   `.get("retry-after")`).
3. `attempt` loop (l.52): replace the fixed sleep with `time.sleep(next_delay(last.retry_after, policy,
   attempt_idx))`.
4. Import `should_retry, parse_retry_after, next_delay` from `polyfetch_scrape.retry`.
5. **TDD** (mirror l.217): a 503 response then a 200 → retries and succeeds (`page.goto.call_count == 2`);
   persistent 503 → `FetchError` after `max_attempts`; (optional) Retry-After honored via monkeypatched
   `time.sleep`. Keep `_attempt_once` under complexity 15. `CHANGELOG.md ### Fixed`. `Closes #84`.

**Verify:** `make ci` green; a 503 on the playwright tier now retries per policy instead of being returned.

## Unit 2 — #85 conditional-GET CLI flags · `feat/cli-conditional-get`

**Steps**

1. `cli.py fetch_cmd`: add `--etag` (`str | None = None`) and `--if-modified-since` (`str | None = None`)
   `typer.Option`s (mirror the #94 `--wait-*` style); thread `etag=…, last_modified=…` into the `fetch(...)`
   call. No `client.py` change (kwargs already exist).
2. **Tests** (`tests/test_cli.py`, mirror `test_fetch_render_flags_build_render_options`): the flags reach
   `fetch()` as `etag` / `last_modified`.
3. Docs: `USING.md` fetch-flags line + a README CLI example + `CHANGELOG.md ### Added`. `Closes #85`.

**Verify:** `make ci` green; `polyfetch fetch <url> --etag '"abc"'` sends `If-None-Match` (→ `status=304`
on a match).

## Unit 3 — #39 + #36 empirical scraping-landscape tables (merge) · `docs/scraping-landscape-empirical`

One PR: add the two empirical anti-bot tables to `docs/scraping-landscape.md`'s "Empirical findings"
subsection with first-party framing. `CHANGELOG.md ### Added` (docs). `Closes #39`, `Closes #36`.

**Verify:** `markdownlint-cli2 docs/scraping-landscape.md` + `lychee --config lychee.toml
docs/scraping-landscape.md` clean.

## Unit 4 — #55 README doc-structure canon · `docs/readme-canon`

Adopt the canonical structure per the checklist in issue #55's comment (add `## What` / `## Why` / standalone
`## License`; fix section order; move `## Public API` depth to `docs/`). Largest doc churn + partly
subjective, so sequenced **last**. `Closes #55`.

**Verify:** `markdownlint-cli2 README.md` + `lychee --config lychee.toml README.md` clean.

---

## Deferred / later (not in this batch)

- **Batch B (medium):** #46 (POST/PUT body — httpx/curl only, playwright is GET-only), #80
  (`min_tier`/`max_tier` escalation cap), #49 (per-host throttle), #33 (sitemap helper — **`defusedxml`** per
  AGENT_LEARNINGS), #32 (github wrapper — `gh search`/REST, maybe downstream).
- **Deferred:** #59 (headed manual-takeover), #72 (`ui_render` contrib), #89 (patents — spike first),
  #60 (UI tracker), #105 (base64 screenshot FR, deferred from #94).

## Git / sequencing

One branch/PR per unit; topical commits by concern; `make validate` **and** `make ci` green before push
(`gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`); open PR (`Closes #NN`); **squash-merge only if all CI checks
pass — never `--admin`**; `--delete-branch` + `git fetch --prune`; keep `main` the only local branch; update
`CHANGELOG.md [Unreleased]` and keep `USING.md` in lockstep for CLI-surface changes (#85).
