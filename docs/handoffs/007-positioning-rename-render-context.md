# Handoff — 007 · Positioning + `patchright` rename + emulation/video

## Onboard

Full plan + code/file/source map: **[`docs/plans/007-positioning-rename-render-context.md`](../plans/007-positioning-rename-render-context.md)** — read it; it has the anchors so you don't re-explore. Repo is clean on `main` @ `6132e38`; nothing started.

**One-paragraph why:** a long positioning discussion + issue triage produced three coupled work items — (1) clarify the value prop around **two layers** (core `fetch()` engine vs. a **scripting substrate** you drive on `render_session().page`), neutral tone; (2) rename the mislabelled browser tier **`playwright`→`patchright`** (the engine is Patchright, a stealth Playwright fork; the API just *labels* it `playwright`); (3) build the **emulation/video** `RenderOptions` knobs consumers keep re-filing (#148/#154/#155/#125/#122).

**Load-bearing insight** driving the boundary: `new_context()`-time options (device/viewport/`color_scheme`/UA/locale/`record_video_dir`) **cannot** be set via the `.page` escape hatch post-hoc → they **must** be core `RenderOptions`, not "just script it." Everything post-context (clicks, screenshots, `aria_snapshot`) stays scriptable.

## How to handle (this repo's policy)

- Everything via `make`/`uv run` (never bare pip/pytest/ruff/pyright/polyfetch); `make validate` green before "done"; scriv fragment per non-trivial change (`make changelog_new`).
- Git: branch per concern, topical commits, squash-merge on green CI, delete branch. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN` (App token lacks repo scope; OAuth login has it).
- **CodeQL is a required check** — never `"<url>" in x` (even in test asserts; use `==`); verify `gh pr checks` before merge.
- **GitHub Actions webhook delivery was flaky** (dropped PR/push events → no runs). If checks don't appear, re-trigger (close/reopen the PR, or push an empty commit) or wait; if merge is blocked, it may be a conflict — merge `main` in and resolve.

## Sequence (do in order)

1. **Wave 0** — `#146` (doc venv-borrow, likely folds into PR B), `#145` (doctor/ensure-chromium), `#105`/`docs/plans/006` (screenshot_b64) → this unblocks **Dependabot #139** (patchright 1.61.2), which Wave 2 wants.
2. **Wave 1 · PR A** — the `playwright`→`patchright` rename (deprecated alias; §"PR A" source map in the plan). Do this before docs so PR B references the final name.
3. **Wave 1 · PR B** — the two-layer positioning docs (README spine + compare + two-bucket "does not do" + architecture boundaries/no-pydantic + drop "hostile"/"the moat").
4. **Wave 2** — emulation+video → core `RenderOptions` (both `new_context()` sites; `Response.video_path`).
5. **Cleanup + enhancements** (plan §Cleanup/Enhancements) — consolidate #148/#154/#155 + #122/#125; **dedup the SSRF guard** (easter_hunt `orchestrator.py:22` → `utils/_ssrf.check_ssrf`); open the pydantic tracking issue; comment #127 (recipe); **close #60**; #89 spike. Then **cut `v0.7.0`** around PR A (breaking rename; migration note) and add a **scripting cookbook** so the "scripts" layer is real.

See the plan's **§Strategic — estate contract**: consumers keep re-filing the same substrate needs (emulation/video/ui-check/doctor) and dropping to raw patchright. Draw the line once — polyfetch owns the *substrate* (engine + `new_context()` knobs + DX), consumers own app-specific e2e — to stop the N-repo drift.

## Open decisions (already made — don't re-litigate)

- Rename **and** clarify (not either/or); keep `"playwright"` as a deprecated input alias.
- **Document** the no-pydantic/no-pydantic-settings choice (don't adopt) **+ open a tracking issue** (open-question framing).
- Emulation/video = **core**; a11y = **scripted recipe**; #60 = **close**.

## State at handoff (2026-07-13, `main` @ 6132e38, v0.6.0)

- Merged this session: #149 (meta), #150 (show-hn draft), #151 (screencast), #152 (**#135** structured discovery). Closed: #134 (YAGNI), #72 (→#144). Created: #153 (structured-first tracker).
- Open (ours): #148 #147 #146 #145 #144 #132 #127 #125 #122 #105 #89 #60 #59 #154 #155 #153. Dependabot: **#139** (red until #105/006's `bulk` complexity fix).
- Nothing on branches; no WIP.
