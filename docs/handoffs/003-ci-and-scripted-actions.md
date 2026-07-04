# Handoff — 003 CI workflow (#98) + scripted playwright actions (#71)

**Plan:** `docs/plans/003-ci-and-scripted-actions.md` · **Status:** planned, not started ·
**Repo:** `main` (v0.5.0 released) · **Issues:** [#98](https://github.com/qte77/polyfetch-scrape/issues/98), [#71](https://github.com/qte77/polyfetch-scrape/issues/71).

## Onboard

Two **independent** tasks. **Read the plan's "Source map" table first** — it names every file, the
functions/anchors, and the sibling CI reference, so you execute with `grep`, not a fresh Explore pass.
Don't re-map the codebase.

- **#98** = the repo runs **no Python CI** (only markdown/links lint). Add a check-only `make ci` recipe
  + `.github/workflows/test.yml` that runs it. Key gotcha: `make lint_src` **mutates** — CI must use
  check-only commands (`ruff format --check`), hence the new `make ci`.
- **#71** = add `RenderAction` + `actions` to `RenderOptions` and run them (click/fill/…) **before**
  `_apply_waits` in `playwright_backend._attempt_once`. It's a clean extension of the #67/#68 surface.

## How to handle (this repo's policy)

1. **One branch per issue** (`ci/test-workflow`, `feat/tier3-actions`); topical commits by concern.
2. **Strict TDD** for #71 (model behavior → red → green); #98 is CI/config (no unit tests, but `make ci`
   must run green locally). Assume strict lint + typing + security always.
3. `make validate` green **before** pushing. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`.
4. Open a PR, then **squash-merge ONLY if all CI checks pass — never `--admin` / never bypass.**
5. `--delete-branch` on merge; `git fetch --prune`; keep `main` the only local branch.
6. Before "done": update `CHANGELOG.md [Unreleased]`, README (only #71 touches API surface), and confirm
   url/env/cli coverage. Close the issue via the PR (`Closes #NN`).

## Resume

**Do #98 first** (it makes every later PR genuinely test-gated), then #71. Both are fully specified with
anchors in the plan. After #71, the remaining tier-3 item is **#59** (headed manual-takeover). Releases
are automated now — see README "Versioning" (bump-version → PAT-merge → tag-release).
