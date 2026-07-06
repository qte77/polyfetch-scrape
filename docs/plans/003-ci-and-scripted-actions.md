# 003 — CI (#98) + scripted actions (#71) + agent-facing CLI contract (#94, #101, USING.md/#41)

> Status: **complete** — all units merged to `main`: USING.md/#41 (PR #102), #98 CI (#103), #101 structured errors (#104), #94 CLI render flags (#106), #71 scripted actions (#107). Deferred: base64 screenshot in `--json` (#105). Handoff: `docs/handoffs/003-ci-and-scripted-actions.md`.
> Repo `main @ cd061c7` (or later), **v0.5.0 released**. Independent units — the sections below are the as-executed record.

## Context

Follow-ups after the v0.5.0 cycle. #98/#71 are the original pair; #94/#101/USING.md were folded in this
session once **agents became the framing primary users** (the CLI+JSON is their public API):

- **#98** — polyfetch runs **no Python validation in CI**. PR checks are only `lint / markdown`,
  `lint / links` (org reusable + `lint-md-links.yml`) and CodeFactor. Tests / ruff / pyright /
  complexity run **only locally** via `make validate`, so a PR that breaks tests can still go green.
- **#71** — the playwright tier can render + wait + screenshot (shipped #67/#68 as `RenderOptions`),
  but can't **drive** the page (click/select/fill) before capture. Next rung of tier-3 depth.
- **#94** — `RenderOptions` (wait/screenshot) is Python-only; the CLI can't express it. For env-borrow
  **agent** consumers (`USING.md`) the CLI *is* the API — capability not on a flag is unreachable.
  Elevated from "out of scope" to a unit here.
- **#101** — CLI errors are inconsistent + unparseable: `fetch` prints `FetchError: <msg>` to stderr
  (ignores `--json`); `bulk` embeds `type(exc).__name__` in a string. Agents need typed
  `{error_type, status}` to branch retry-vs-give-up-vs-escalate.
- **USING.md / #41** (implemented this session) — machine-facing "use without installing"
  (`uv run --directory` env-borrow) contract. Establishes the CLI+JSON as the stable public surface that
  #94/#101 harden; its `## Output schema` / `## Errors & exit codes` must be kept in sync when they land.

## Source map — read these, don't re-explore

**Repo facts:** src layout `src/polyfetch_scrape/`; `make`-driven (AGENTS.md: never bare
`pip`/`pytest`/`ruff`/`pyright`); pyright strict; complexipy threshold 15; coverage ≥ 90; `gh` needs
`env -u GH_TOKEN -u GITHUB_TOKEN`. Tests mock the browser (no network in `make test`).

| File / path | What's there (anchors) |
|---|---|
| `src/polyfetch_scrape/render_options.py` | `RenderOptions` frozen dataclass — fields `wait_until` (Literal domcontentloaded/load/networkidle), `wait_for_selector`, `wait_for_function`, `screenshot`. **#71 adds `RenderAction` + `actions` here.** |
| `src/polyfetch_scrape/_backends/playwright_backend.py` | `attempt(...,render: RenderOptions\|None=None)` → normalizes `opts` → loop → `_attempt_once(browser,url,headers,timeout_ms,opts)`. `_attempt_once`: `page.goto(url,wait_until=opts.wait_until)` → fingerprint(403) → `raise_for_terminal_status` → **`_apply_waits(page,opts,timeout_ms)`** → `page.content()` + `_capture_screenshot(page,opts.screenshot)`. Helpers `_apply_waits`, `_capture_screenshot` at module end. **#71 inserts `_apply_actions(...)` BEFORE `_apply_waits`.** |
| `src/polyfetch_scrape/client.py` | `fetch(...,render=None)`; reconciles `render = render or RenderOptions(wait_for_selector=...)`; threads `render=` to playwright at the escalation call + `_run_single_tier`. `__all__` exports `RenderOptions`. **No flow change for #71** (render already flows). |
| `src/polyfetch_scrape/__init__.py` | package `__all__` re-exports `RenderOptions` from `client`. **#71: add `RenderAction` to both `__all__`s.** |
| `tests/test_playwright_backend.py` | Mock chain `_make_pw_chain(monkeypatch,...)` (~line 17) returns `(page, response)`; `page` is `MagicMock(spec=pw_sync.Page)`. Existing `test_playwright_backend_uses_wait_until_from_render` / `_waits_for_function` / `_captures_*_screenshot` are the **templates to mirror** for action tests. |
| `src/polyfetch_scrape/cli.py` | Typer CLI. `_summarize` (l.39-46 → `url/status/backend/bytes/content_type`), `_format_text` (l.49-55), `fetch_cmd` error path (l.92-94: `FetchError: <msg>` to stderr, **ignores `--json`**), `bulk._run_one` error (l.111-116: `{"url","error":"Type: msg","backend":None}`), `bulk` (l.119-154). **#101 makes both error shapes `{error_type,status}` + honors `--json`; #94 adds render flags to `fetch_cmd`.** |
| `src/polyfetch_scrape/errors.py` | `FetchError` + `AuthRequired` (401/407), `GoneError` (404/410), `LegalBlock` (451). **#101 maps `type(exc).__name__` → `error_type`.** |
| `src/polyfetch_scrape/response.py` | `Response` incl. `permanent_redirect_to` (301/308 target) + `screenshot` (PNG bytes). **#101: consider adding `permanent_redirect_to` to `_summarize`; #94 surfaces `screenshot`.** |
| `tests/test_cli.py` | `CliRunner`; `_ok(url,status)` helper (l.15); monkeypatches `polyfetch_scrape.cli.fetch`. **#101 UPDATES `test_fetch_exits_1_on_fetcherror` (l.73-82) + `test_bulk_continues_on_error_and_exits_1` (l.118-140) to the new error schema; #94 mirrors `test_fetch_json_flag_*` for render-flag tests.** |
| `USING.md` | Agent/no-install contract: `## Output schema` + `## Errors & exit codes`. **Keep in lockstep with #94 (new flags) + #101 (error schema).** |
| `Makefile` | Recipes `type_check` (`uv run pyright src`), `complexity` (`uv run complexipy -q .`, default threshold 15), `test_coverage` (`uv run pytest ...`), `validate` (chains them). **⚠️ `lint_src`/`lint_tests` MUTATE (`ruff format .` + `--fix`) — unusable for CI.** |
| `pyproject.toml` | `[tool.coverage] fail_under = 90`; `[tool.pytest] addopts = "... -m 'not e2e'"` (e2e opt-in); `[tool.ruff.lint] select` includes `S` (security); `[tool.bumpversion]` (release pipeline). |
| `.github/workflows/` | `lint-md-links.yml`, `bump-version.yaml`, `tag-release.yaml` (SHA-pinned `actions/checkout@df4cb1c…` v6.0.3, `astral-sh/setup-uv@fac544c…` v8.2.0). **No test/lint workflow — #98 adds it.** |
| `../gha-rxiv-feed-action/.github/workflows/{test.yml,ruff.yml}` | Sibling CI reference: checkout+setup-uv (same SHAs, `enable-cache: true`) → `uv sync --frozen` → `uv run pytest` / `uv run ruff check .` + `ruff format --check .`. |

---

## #98 — CI test/lint workflow

**Load-bearing decision:** `make lint_src`/`lint_tests` mutate, so they can't gate CI. Add a
**check-only** `make ci` recipe (keeps make-only discipline, single source of truth), and have CI call it.

**Steps**
1. `Makefile`: add `ci:` target — `uv run ruff check .` + `uv run ruff format --check .` +
   `uv run pyright src` + `uv run complexipy -q .` + `uv run pytest` (coverage gate + `not e2e`
   default already in `pyproject.toml`). Copy exact flags from the existing `type_check`/`complexity`/
   `test_coverage` recipe bodies.
2. **new** `.github/workflows/test.yml`: `on: [push→main, pull_request→main, workflow_dispatch]`; one
   job — checkout + setup-uv (SHA-pinned as above, `enable-cache: true`) → `uv sync --frozen` → `make ci`.
   Do **not** run `make test_e2e`.
3. `CHANGELOG.md` `### Added` (CI workflow). No README/API change. Closes #98.

**Verify:** PR shows the `test.yml` check passing. Local: `make ci` exits 0; add a format error →
`ruff format --check` fails (proves it gates). No `--admin` needed to merge once green.

---

## #71 — scripted pre-capture actions (click/select/fill before capture)

**Design:** add `actions: tuple[RenderAction, ...] = ()` to `RenderOptions`; typed `RenderAction`
(NOT dicts — pyright-strict) verbs `click`(selector) / `click_text`(text) / `fill`(selector,value) /
`wait_for_selector`(selector) / `wait_ms`(int). Run **in order, BEFORE** `_apply_waits` (drive → settle
→ capture).

**Steps**
1. `render_options.py`: `RenderAction` frozen dataclass (`verb: Literal[...]`, `selector/text/value:
   str|None=None`, `ms: int|None=None`) + `actions` field on `RenderOptions`.
2. `playwright_backend.py`: add helper `_apply_actions(page, actions, timeout_ms)` (next to
   `_apply_waits`, keeps `_attempt_once` < complexity 15); **call it right before `_apply_waits`**.
   Mapping: `click`→`page.click(selector,timeout=…)`, `click_text`→`page.get_by_text(text).click(timeout=…)`,
   `fill`→`page.fill(selector,value,timeout=…)`, `wait_for_selector`→`page.wait_for_selector(…)`,
   `wait_ms`→`page.wait_for_timeout(ms)`.
3. Export `RenderAction` from `client.py __all__` + `__init__.py __all__` (mirror `RenderOptions`).
4. **Strict TDD** in `tests/test_playwright_backend.py`: assert actions fire **in order** via
   `_make_pw_chain` (`page.mock_calls` sequence, or per-mock `assert_called_once_with`). Mirror the
   `wait_until`/`wait_for_function` tests. No dedicated test for the plain dataclass (trivial).
5. Docs: README Public API `RenderOptions(...)` block (add `actions=`); `CHANGELOG.md` `### Added`.
   Closes #71. CLI flags out of scope (tracked #94).

**Verify:** `make validate` green. Smoke (needs `make setup_browsers`): a page whose control changes on
click → `fetch(url, tier="playwright", render=RenderOptions(actions=(RenderAction("click","<sel>"),),
screenshot="viewport"))` → screenshot shows the post-click state.

## #94 — expose render options on the CLI (agent-reachable)

**Why:** env-borrow agents (`USING.md`) reach polyfetch only through the CLI; `RenderOptions` is
Python-only today, so the primary consumer can't render without an in-clone script.

**Steps**

1. `cli.py fetch_cmd`: add `--screenshot [viewport|<css>]`, `--wait-until [domcontentloaded|load|networkidle]`,
   `--wait-for-function <js>` (keep `--wait-for-selector`); build `RenderOptions(...)` from them and pass
   `render=` to `fetch()`. Scalar flags only — `actions` (#71) stay Python-only (structured, not flag-shaped).
2. `--screenshot` output: write PNG to `--screenshot-out <path>` if given, else base64 as `screenshot_b64`
   in the `--json` payload. Leave `_summarize` text output unchanged.
3. `tests/test_cli.py` (mirror `test_fetch_json_flag_*`): assert flags build the right `RenderOptions` and a
   screenshot round-trips.
4. Docs: `USING.md` `## Output schema` + flag list; README Public API note; `CHANGELOG.md ### Added`. Closes #94.

**Verify:** `make validate` green; `polyfetch fetch <js-url> --tier playwright --screenshot viewport --json`
returns the shot; `USING.md` matches the new flags.

---

## #101 — structured JSON errors (fetch/bulk parity)

**Design:** on `--json`, both commands emit `{"url","error_type","status","message"}`; exit stays 1.
`error_type` = the public exception class name (`errors.py`); `status` = terminal HTTP status or `null`.

**Steps**

1. `cli.py`: helper `_error_payload(url, exc) -> dict` → `{url, error_type: type(exc).__name__,
   status: <int|None>, message: str(exc)}` (derive `status` from the terminal-status message, else null).
2. `fetch_cmd` (l.92-94): on `FetchError`, if `--json` print `_error_payload(...)` to **stdout** + exit 1,
   else keep the stderr text line. `bulk._run_one` (l.111-116): return `_error_payload(...)` (drop the
   `"Type: msg"` string) so lines share the schema.
3. **TDD** in `tests/test_cli.py`: UPDATE `test_fetch_exits_1_on_fetcherror` (l.73-82) to assert the JSON
   shape under `--json`; UPDATE `test_bulk_continues_on_error_and_exits_1` (l.118-140) for `error_type`/`status`;
   add one case per class (`GoneError` 404, `AuthRequired` 401, `LegalBlock` 451).
4. Docs: `USING.md` `## Errors & exit codes` (replace the "does not yet honor `--json`" note); README;
   `CHANGELOG.md` (`### Added` new schema / `### Changed` `bulk` error shape). Closes #101.

**Verify:** `make validate` green; `polyfetch fetch <404-url> --json` → `{"error_type":"GoneError","status":404,...}`
on stdout, exit 1; bulk lines match; `USING.md` updated.

---

## Git / sequencing

Independent — one branch per unit (`docs/using-contract` [USING.md/#41, ready now], `ci/test-workflow` [#98],
`feat/tier3-actions` [#71], `feat/cli-render-flags` [#94], `feat/cli-structured-errors` [#101]). Topical
commits; `make validate` green before push; open PR (`Closes #NN`); **squash-merge only if CI checks pass —
no `--admin`**; delete branch + `git fetch --prune`. Recommended order: **USING.md/#41 PR first** (already
implemented), then **#98** (gates the rest), then **#101** + **#94** (the agent CLI contract), then **#71**.

## Out of scope

Deferred: #59 headed manual-takeover (last tier-3); CodeQL workflow; `actions` on the CLI (#71 stays
Python-only — structured, not flag-shaped).
