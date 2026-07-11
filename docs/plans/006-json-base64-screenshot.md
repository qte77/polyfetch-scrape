# 006 — #105 base64 screenshot in `fetch --json` (`screenshot_b64`)

> Status: **planned, not started.** Handoff: `docs/handoffs/006-json-base64-screenshot.md`.
> Repo `main` (v0.6.0 released). CI gates every PR: `Test / ci` + `CodeQL` + `lint`.
> **Changelog is scriv now** — `make changelog_new`, never a manual `CHANGELOG.md` edit.

## Context

`fetch --json` emits `{url, status, backend, bytes, content_type}` (`_summarize`). #105 surfaces the
playwright-tier screenshot **inline** as base64 (`screenshot_b64`) so env-borrow / agent consumers get
the PNG in the JSON without `--screenshot-out` writing a file (deferred from #94). Fold in the
`--browser` → `StrEnum` tidy (drops a `# type: ignore`).

**Also fold in (unblocks Dependabot #139):** extract `cli.py:bulk`'s `workers > 1` `ThreadPoolExecutor`
branch into a `_run_pool` helper. `complexipy` 6.0.1 (the major bump in #139) scores `bulk` at **18** (> 15);
5.4.0 passed it. Since #105 already touches `cli.py`, do the extraction here so the whole #139 group
(incl. **patchright 1.61.2**, wanted for #127/#132) can rebase green and merge. Behavior-preserving —
existing `test_cli.py` bulk tests are the regression net (no new red-first test needed for the extraction).

## Source map — read these, don't re-explore

**Repo facts:** src layout `src/polyfetch_scrape/`; make-driven (never bare `pip`/`pytest`/`ruff`/`pyright`);
pyright **strict** `include=["src"]` (tests NOT type-checked); complexipy ≤ 15; cov ≥ 90; e2e opt-in.
`gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`.

| File / anchor | What's there / what to do |
|---|---|
| `src/polyfetch_scrape/cli.py` `_summarize` **l.59-66** | builds the `--json` dict; **shared with `bulk`** (which has no screenshot). Add `screenshot_b64` only on the **fetch** path — either an optional 2nd builder or add the key in `fetch_cmd` before the json emit (l.197-198). |
| `cli.py` `fetch_cmd` **l.88-198** | `--screenshot` l.109-115, `--screenshot-out` l.116-119, `RenderOptions(...)` build l.160-165, screenshot-out write l.187-188, json emit **l.197-198**. Base64 `resp.screenshot` into the payload before l.198. |
| `cli.py` `browser: str = "chrome"` **l.94** + `# type: ignore[arg-type]` **l.172** | **StrEnum tidy:** add `_BrowserChoice(StrEnum)` (`chrome`/`firefox`) mirroring `_TierChoice` **l.20-33** + an `_as_browser` bridge; retype the param; drop the l.172 ignore. (Bonus: `--wait-until` StrEnum drops the l.161 ignore too — optional.) |
| `cli.py` `bulk` **l.217-263** (the `workers > 1` `ThreadPoolExecutor` block **l.251-260**) | **Complexity fix (unblocks #139):** extract the worker-pool branch into a `_run_pool(urls, *, …) -> None` helper so `bulk` drops back under complexipy 15 (it scores 18 under complexipy 6.0.1). Behavior-preserving. |
| `src/polyfetch_scrape/response.py` `Response.screenshot: bytes\|None` | the bytes source. Surface the **single** `screenshot` only — the plural `Response.screenshots` is library-only (no CLI flag) → out of scope. |
| `tests/test_cli.py` | existing `--screenshot`/`--screenshot-out` tests (~l.96/106/209-235). Add the 3 tests below (no fixture change — the CLI tests monkeypatch `fetch`). |
| `USING.md` `## Output schema (--json)` **l.40-49** | add `screenshot_b64` to the documented schema + a one-line note. |

## Design

- **`screenshot_b64`**: `base64.b64encode(resp.screenshot).decode("ascii")` when `resp.screenshot is not None`;
  add to the **fetch** json payload only. Key **absent** when no screenshot (see decision #1).
- **`--browser` StrEnum**: `_BrowserChoice(StrEnum){chrome,firefox}` + `_as_browser(choice) -> Browser`
  (mirror `_as_tier` l.31-33); replace `browser: str = "chrome"` and drop `# type: ignore[arg-type]` l.172.

## Strict TDD (red first) — `tests/test_cli.py` (`cli` IS a module → real, non-trivial tests)

1. **`test_fetch_json_includes_screenshot_b64`** — monkeypatch `fetch` → `Response(..., screenshot=b"\x89PNG-x")`;
   run `fetch URL --json --screenshot viewport --tier playwright`; parse stdout JSON; assert
   `base64.b64decode(payload["screenshot_b64"]) == b"\x89PNG-x"`.
2. **`test_fetch_json_omits_screenshot_b64_when_absent`** — `screenshot=None` → `"screenshot_b64" not in payload`.
3. **`test_browser_flag_rejects_invalid_choice`** — `--browser safari` → non-zero exit (typer validates the StrEnum); `--browser firefox` → ok.
- Regression: existing `--screenshot-out` + json/text tests stay green.

## Docs

- **scriv fragment** (`make changelog_new`) `### Added` — `screenshot_b64` in `fetch --json` + `--browser` StrEnum. `Closes #105`.
- `USING.md` `--json` schema — add `screenshot_b64`.
- `docs/roadmap.md` — mark #105 shipped in the relevant facet. No architecture/userstory change (CLI surfacing of an existing feature).

## Verify → CI-gated PR

1. `make validate` **and** `make ci` green (ruff, pyright strict 0, complexipy < 15, cov ≥ 90).
2. `/security-review` — expected clean (base64 of local bytes; no new sink).
3. `markdownlint-cli2 "*.md"` (root glob = CI scope) + `lychee --config lychee.toml <touched>`.
4. **Live e2e:** `uv run polyfetch fetch https://quotes.toscrape.com/js/ --tier playwright --screenshot viewport --json | jq -r .screenshot_b64 | base64 -d | file -` → `PNG image data`.
5. Branch `feat/json-screenshot-b64`; topical commits (cli+tests / docs); PR `Closes #105`; squash-merge on green (not a release → normal squash); `--delete-branch` + `git fetch --prune`.

## Open decisions (surface via AskUserQuestion at kickoff)

1. `screenshot_b64` **absent** vs. `null` when no screenshot (plan assumes absent).
2. Surface the plural `Response.screenshots` as a `screenshots_b64` dict too? (Needs a CLI flag; likely **no** — single only, YAGNI.)
3. Also StrEnum `--wait-until` (bonus type-ignore removal) or just `--browser`?
