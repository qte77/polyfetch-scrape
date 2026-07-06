# Handoff — 003 CI (#98) + scripted actions (#71) + agent CLI contract (#94, #101, USING.md/#41)

**Plan:** `docs/plans/003-ci-and-scripted-actions.md` · **Status:** in progress (USING.md/#41 done, pending PR; #98/#71/#94/#101 to do) ·
**Repo:** `main` (v0.5.0 released) · **Issues:** [#98](https://github.com/qte77/polyfetch-scrape/issues/98), [#71](https://github.com/qte77/polyfetch-scrape/issues/71), [#94](https://github.com/qte77/polyfetch-scrape/issues/94), [#101](https://github.com/qte77/polyfetch-scrape/issues/101).

## Onboard

**Independent** units — agents are the framing primary users; the CLI+JSON they consume is the public
surface that issues #94/#101 harden. **Read the plan's "Source map" table first** — it names every file, the
functions/anchors, and the sibling CI reference, so you execute with `grep`, not a fresh Explore pass.
Don't re-map the codebase.

- **#98** = the repo runs **no Python CI** (only markdown/links lint). Add a check-only `make ci` recipe
  plus a `.github/workflows/test.yml` that runs it. Key gotcha: `make lint_src` **mutates** — CI must use
  check-only commands (`ruff format --check`), hence the new `make ci`.
- **#71** = add `RenderAction` + `actions` to `RenderOptions` and run them (click/fill/…) **before**
  `_apply_waits` in `playwright_backend._attempt_once`. It's a clean extension of the #67/#68 surface.
- **#94** = expose render options as `fetch` CLI flags (`--screenshot`/`--wait-until`/`--wait-for-function`)
  so env-borrow agents can render without an in-clone script. Scalars only; `actions` stay Python-only.
- **#101** = structured JSON errors on `fetch`/`bulk` (`{error_type,status}`, honor `--json`) — today
  `fetch` prints stderr text (ignores `--json`) at `cli.py:92-94`; `bulk` uses a string at `cli.py:115`.
- **USING.md / #41** = **DONE** this session (working tree): the `uv run --directory` no-install contract;
  keep its `## Output schema` / `## Errors` in sync when #94/#101 land. Ships in the `docs/using-contract` PR.

## How to handle (this repo's policy)

1. **One branch per unit** (`docs/using-contract` [USING.md/#41], `ci/test-workflow` [#98], `feat/tier3-actions` [#71], `feat/cli-render-flags` [#94], `feat/cli-structured-errors` [#101]); topical commits by concern.
2. **Strict TDD** for #71 (model behavior → red → green); #98 is CI/config (no unit tests, but `make ci`
   must run green locally). Assume strict lint + typing + security always.
3. `make validate` green **before** pushing. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`.
4. Open a PR, then **squash-merge ONLY if all CI checks pass — never `--admin` / never bypass.**
5. `--delete-branch` on merge; `git fetch --prune`; keep `main` the only local branch.
6. Before "done": update `CHANGELOG.md [Unreleased]`, README + `USING.md` (#71/#94/#101 all touch the
   CLI/API surface), and confirm url/env/cli coverage. Close the issue via the PR (`Closes #NN`).

## Resume

**USING.md/#41 PR first** (already implemented — `docs/using-contract`), then **#98** (gates the rest),
then **#101** + **#94** (the agent CLI contract), then **#71**. All fully specified with anchors in the
plan. After #71, the remaining tier-3 item is **#59** (headed manual-takeover). Releases are automated
now — see README "Versioning" (bump-version → PAT-merge → tag-release).
