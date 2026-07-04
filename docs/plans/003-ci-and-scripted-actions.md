# 003 — Python CI workflow (#98) + scripted playwright actions (#71)

> Status: **planned, not started.** Handoff: `docs/handoffs/003-ci-and-scripted-actions.md`.
> Repo `main @ cd061c7` (or later), **v0.5.0 released**. Two **independent** units — do in either order.

## Context

Two follow-ups surfaced after the v0.5.0 cycle:

- **#98** — polyfetch runs **no Python validation in CI**. PR checks are only `lint / markdown`,
  `lint / links` (org reusable + `lint-md-links.yml`) and CodeFactor. Tests / ruff / pyright /
  complexity run **only locally** via `make validate`, so a PR that breaks tests can still go green.
- **#71** — the playwright tier can render + wait + screenshot (shipped #67/#68 as `RenderOptions`),
  but can't **drive** the page (click/select/fill) before capture. Next rung of tier-3 depth.

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
| `Makefile` | Recipes `type_check` (`uv run pyright src`), `complexity` (`uv run complexipy ... -mx 15`), `test_coverage` (`uv run pytest ...`), `validate` (chains them). **⚠️ `lint_src`/`lint_tests` MUTATE (`ruff format .` + `--fix`) — unusable for CI.** |
| `pyproject.toml` | `[tool.coverage] fail_under = 90`; `[tool.pytest] addopts = "... -m 'not e2e'"` (e2e opt-in); `[tool.ruff.lint] select` includes `S` (security); `[tool.bumpversion]` (release pipeline). |
| `.github/workflows/` | `lint-md-links.yml`, `bump-version.yaml`, `tag-release.yaml` (SHA-pinned `actions/checkout@df4cb1c…` v6.0.3, `astral-sh/setup-uv@fac544c…` v8.2.0). **No test/lint workflow — #98 adds it.** |
| `../gha-rxiv-feed-action/.github/workflows/{test.yml,ruff.yml}` | Sibling CI reference: checkout+setup-uv (same SHAs, `enable-cache: true`) → `uv sync --frozen` → `uv run pytest` / `uv run ruff check .` + `ruff format --check .`. |

---

## #98 — CI test/lint workflow

**Load-bearing decision:** `make lint_src`/`lint_tests` mutate, so they can't gate CI. Add a
**check-only** `make ci` recipe (keeps make-only discipline, single source of truth), and have CI call it.

**Steps**
1. `Makefile`: add `ci:` target — `uv run ruff check .` + `uv run ruff format --check .` +
   `uv run pyright src` + `uv run complexipy src -mx 15` + `uv run pytest` (coverage gate + `not e2e`
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

## Git / sequencing

Independent — one branch per issue (`ci/test-workflow`, `feat/tier3-actions`). Topical commits;
`make validate` green before push; open PR; **squash-merge only if CI checks pass — no `--admin`**;
delete branch + `git fetch --prune`. Recommended order: **#98 first** (gates future PRs), then #71.

## Out of scope

#59 headed manual-takeover (last tier-3); #94 CLI render flags; CodeQL workflow.
