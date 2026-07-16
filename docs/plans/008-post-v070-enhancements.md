# 008 — Post-v0.7.0 high-ROI enhancements

> Status: **planned, not started.** Repo clean on `main` @ `dfbba22` (v0.7.0 shipped).
> Handoff: `docs/handoffs/008-post-v070-enhancements.md`. Line numbers are as of `dfbba22` —
> re-grep to confirm before editing. The **Source map** means the next session need not re-explore.

## Context

v0.7.0 shipped the whole 007 plan (patchright rename, two-layer positioning, emulation/video → core
`RenderOptions`, docs completeness, Actions hardening, e2e-target refresh). This is the deferred
**high-ROI** backlog from the post-release review, prioritized by ROI/effort. Each is an independent
PR gated on `make validate` + green CI, squash-merged (repo workflow).

**Reuse discipline:** the emulation/video path already exists (`RenderOptions` fields +
`context_kwargs` in `_backends/patchright_backend.py`); the e2e suite already runs weekly. Prefer
extending these over new surfaces.

## Prioritized roadmap

| # | Item | ROI | Effort | Verdict |
|---|---|---|---|---|
| 1 | Scheduled browser e2e | H | — | **Already done** — verify-only (+ optional notify) |
| 2 | `#132` full_page screenshots | M | L | Re-probe first; build only if 1.61.2 fixed it |
| 3a | Estate "consuming across the estate" doc | H | L | **Do now** |
| 3b | `#144` minimal ui-check helper | M | M | Defer (AHA — needs ≥2 repos + stable API) |
| 3c | Verify decidable-line / no-pydantic in architecture.md | — | — | Check-only (landed in #161) |
| 4 | Badge/workflow templating across estate | M | — | Cross-repo; out of this tree |
| op1 | Item 3 — self-signing release commits | H | M | Recommended; blocked on your GPG secret |
| op2 | Org-level Actions policy (allow-list reset) | M | L | Investigate; API-only |

Recommended first slice: **3a (estate doc)** + **op1 (signing, once secret exists)**; then **2**
gated on the full_page re-probe. #1 is already in place.

---

## 1. Scheduled browser e2e — ALREADY DONE (verify only)

`.github/workflows/canonical-probe.yaml` (weekly Mon 06:00 UTC + `workflow_dispatch`) already runs
`make setup_browsers` then `make test_e2e` against the real network — so the full e2e suite, **including
the new `tests/test_e2e.py::test_patchright_emulation_and_video_record_real_webm` guard and the direct
`curl_cffi`/`patchright` capability tests**, runs weekly with no work needed. Its header comment states
a failing PASSING target fails the job → GitHub notifies.

**Optional micro-enhancement (only if desired):** the reusable lint workflow uses a `notify`
job that opens an issue on failure (`qte77/.github/.github/workflows/lint-md-links.yml`, the `notify:`
job with `issues: write`). Mirror that into `canonical-probe.yaml` for an explicit issue-on-decay
instead of relying on the run-failure email. Low value if you already watch Actions.

**Source map:** `.github/workflows/canonical-probe.yaml:36-40` (the `setup_browsers` + `test_e2e`
steps). No source changes.

---

## 2. `#132` full_page screenshots — re-verify, then maybe re-enable

`full_page` is intentionally rejected (documented as "Chromium writes 0 bytes on tall pages") — an
**older-patchright** limitation; v0.7.0 ships patchright **1.61.2**, which may have fixed it.

**Step 1 (gate) — empirical re-probe, no code:** drive `page.screenshot(full_page=True)` against a tall
real page under 1.61.2 and check bytes. Quickest path: a throwaway `uv run python -c` using
`render_session(url).page.screenshot(full_page=True, path=...)`, or add a temporary probe. If it writes
**non-zero** bytes → proceed to Step 2. If still **0** → do NOT build; just update the three doc/comment
sites (below) with a "re-checked 1.61.2 (still 0 bytes)" date and stop.

**Step 2 (only if fixed) — add support (red-first TDD):**

- `src/polyfetch_scrape/_backends/patchright_backend.py` — `capture_screenshot(page, target)` (~`:246-256`):
  currently `if target == "viewport": return page.screenshot()` / else element shot. Add
  `if target == "full_page": return page.screenshot(full_page=True)`.
- `src/polyfetch_scrape/render_options.py` — drop the "full_page unsupported" caveats: `Screenshot`
  docstring (`:33-35`) and `RenderOptions.screenshot` docstring (`:53-54`); no field-type change
  (`screenshot: str | None`, `Screenshot.target: str`).
- `src/polyfetch_scrape/cli.py` — `--screenshot` help (`~:130-136`, the `Annotated[str | None,
  typer.Option("--screenshot", help="...viewport' or a CSS selector...")]`) → mention `full_page`.
- Tests: `tests/test_patchright_backend.py` (mirror `test_patchright_backend_captures_viewport_screenshot`
  — mock `page.screenshot` and assert called with `full_page=True`); an e2e in `tests/test_e2e.py`.
- Docs: `docs/api-reference.md` (Render controls section), `docs/scraping-landscape.md` if it notes the
  limitation, `### Added`/`### Fixed` changelog fragment.

---

## 3. Estate-contract follow-through (007 §Strategic steps 3–5)

**3a — DO NOW: "consuming polyfetch across the estate" doc.** New `docs/estate.md` (or a section in
`USING.md`). Content = the `uv run --directory` env-borrow contract (already in `USING.md` "TL;DR" +
"Why env-borrow") + the **ownership line** (polyfetch owns the substrate: engine + `new_context()`
knobs + install/teardown/capture/SSRF; consumers own app-specific walks/selectors/assertions) + the
promotion rule for when a consumer need becomes core. Cross-link from README **References** list
(`README.md` `## References`, ~`:104-115`, alongside the Architecture/USING links) and from
`docs/architecture.md` "Two layers" section. Reuse the decidable-line test already in
`architecture.md` Invariants (`polyfetch owns the substrate, not app-specific e2e`).

**3b — DEFER (AHA): `#144` minimal ui-check helper.** Extract only render + screenshot + console/404
assert + Make-driveable, and only when **≥2 repos need the identical thing AND the API is stable** (per
007 §"How to move the line"). Not ripe. Keep `#144` backlog with that trigger recorded.

**3c — VERIFY only:** confirm the decidable-line test + no-pydantic invariant landed in
`docs/architecture.md` (they did in #161) — no work.

---

## 4. Badge / workflow templating across the estate — CROSS-REPO

polyfetch's badges + CodeQL + `lint-md-links` calls are aligned to the sibling convention
(`agentic-job-offer-to-application-kit`). Propagating that is an **org-level** task (templatize into
`qte77/.github`, or per repo) — **not in polyfetch's tree**. No polyfetch PR; track as an estate task.

---

## Operational wins (fold in if desired)

**op1 — Self-signing release commits (recommended; removes per-release toil).** `main` enforces
**signed commits via a ruleset**; the `bump-my-version` Docker action commits **unsigned**, so every
release PR is BLOCKED until manually re-signed (`git checkout -B bump-N-main origin/bump-N-main; git
commit --amend --no-edit --reset-author; git push --force-with-lease`). Fix:

- `.github/workflows/bump-version.yaml` — the "Commit, push branch, open PR" step (`:66-88`,
  `git commit -am ... && git push`). Add a `crazy-max/ghaction-import-gpg@<full-sha>` step (import a bot
  key) + `git config commit.gpgsign true` (or `commit -S`). **Also add** `crazy-max/ghaction-import-gpg@*`
  to the Actions allow-list (it's a new third-party action — see the Actions-policy note below) and
  SHA-pin it (the repo requires it).
- **Blocked on you:** create a bot GPG key, add repo secrets `GPG_PRIVATE_KEY` (ASCII-armored) +
  `GPG_PASSPHRASE`, add the public key to the committing GitHub account.
- Action-free alternative: rewrite the commit step to `gh api graphql createCommitOnBranch` (GitHub
  auto-signs; ~40 lines of bash building base64 additions + fragment deletions — test on a live cut).

**op2 — Org-level Actions policy.** The repo allow-list (`patterns_allowed`) self-emptied once this
session (only the verified-creator `astral-sh/setup-uv` survived → `lint/markdown` `startup_failure`).
Check whether an **org-level** Actions policy on the `qte77` account is overriding/resetting the
repo-level one; if so, set allowed-actions at the org level (stable + DRY). API-only, reversible.

---

## Source map (consolidated — grep these, don't re-explore)

- **Actions policy (current):** `allowed_actions: selected` + `sha_pinning_required: true` + github +
  verified allowed; `patterns_allowed = [astral-sh/setup-uv@*, callowayproject/bump-my-version@*,
  DavidAnson/markdownlint-cli2-action@*, lycheeverse/lychee-action@*]`. Managed via
  `gh api --method PUT repos/qte77/polyfetch-scrape/actions/permissions[/selected-actions]`. The
  transitive gotcha: actions **inside** the called `qte77/.github/.github/workflows/lint-md-links.yml`
  reusable workflow (markdownlint + lychee) MUST be whitelisted or that workflow startup-fails.
- **Screenshot capture:** `_backends/patchright_backend.py::capture_screenshot` (~`:246-256`).
- **Render options:** `render_options.py` — `Screenshot` (`:29-41`), `RenderOptions` (`:44-88`,
  emulation/video fields `:82-88`), `ColorScheme` alias (`:9`).
- **CLI:** `cli.py` `fetch_cmd` render flags (`--screenshot` ~`:130-136`; emulation/video flags
  `--device/--viewport/--color-scheme/--user-agent/--locale/--video-out` ~`:190-221`); `--json`
  `screenshot_b64`/`video_path` emit (~`:305-311`); `doctor` command; `bulk` `@app.command()` ~`:230`.
- **e2e:** `tests/test_e2e.py` (module `pytestmark = pytest.mark.e2e`; `test_curl_backend_...`,
  `test_patchright_backend_executes_against_real_target`, `test_patchright_emulation_and_video_record_real_webm`).
- **Release pipeline:** `.github/workflows/bump-version.yaml` (bump + `scriv collect` + open PR — commit
  step `:66-88`), `.github/workflows/tag-release.yaml` (fires on push to main touching `pyproject.toml`).
- **Weekly probe:** `.github/workflows/canonical-probe.yaml:36-40`.

## Verify → CI-gated PR

`make validate` green each PR (pyright-strict, complexipy ≤15, cov ≥90, `filterwarnings=["error"]`);
CI green (ci + CodeQL + `lint/*` reusable workflow — **if `lint/markdown` startup-fails, re-apply the
Actions allow-list**, see the one-liner in the handoff). `env -u GH_TOKEN -u GITHUB_TOKEN gh …`;
squash-merge on green; **main requires signed commits** (your OAuth commits auto-sign; the manual
re-sign dance is only needed for the bot-authored bump branch). `docs/plans/` + `docs/handoffs/` are
**markdownlint-linted** — author these lint-clean (blank lines around headings/tables/fences). For the
full_page / e2e items, verify against a **real browser** (`make setup_browsers`), not just mocks.
