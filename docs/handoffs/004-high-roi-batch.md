# Handoff — 004 remaining high-ROI backlog (#84, #85, #39+#36, #55)

**Plan:** `docs/plans/004-high-roi-batch.md` · **Status:** planned, not started ·
**Repo:** `main` — plan 003 fully merged; **Python CI is live** (`Test / ci` gates every PR).
**Maintainer decisions locked:** #84 = full parity (retry + Retry-After); all four units in scope (incl. #55).

## Onboard

Four **independent** units. **Read the plan's "Source map" table first** — it names every file, the exact
anchors, and the *template* to mirror for each unit, so you execute with `grep`, not a fresh Explore pass.
Don't re-map the codebase.

- **#84** (correctness bug) = the playwright tier returns a **5xx as success** (no retry) while httpx/curl
  retry `{429,500,502,503,504}`. Fix by mirroring `httpx_backend._attempt_once`: add a `should_retry` check +
  a `retry_after` field on playwright's `_Attempt`, and use `next_delay`/`parse_retry_after` from `retry.py`.
- **#85** = `fetch()` already accepts `etag`/`last_modified`; just add `--etag`/`--if-modified-since` CLI
  flags to `cli.py fetch_cmd` and pass them through (mirror the #94 `--wait-*` flags). No `client.py` change.
- **#39 + #36** = one docs PR: two empirical anti-bot tables in `docs/scraping-landscape.md` (close both).
- **#55** = README doc-structure canon (checklist lives in issue #55's comment). Biggest + most subjective —
  do **last**.

## How to handle (this repo's policy)

1. **One branch per issue** (`fix/playwright-5xx-retry`, `feat/cli-conditional-get`,
   `docs/scraping-landscape-empirical`, `docs/readme-canon`); topical commits by concern.
2. **Strict TDD** for #84/#85 — mirror the named template tests in the Source map; assume strict
   lint + typing + security. Keep `_attempt_once` under complexity 15.
3. `make validate` **and** `make ci` green **before** pushing. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`.
4. Open a PR, then **squash-merge ONLY if all CI checks pass — never `--admin`, never bypass.** The
   `Test / ci` check (from #98) runs on the PR itself.
5. `--delete-branch` on merge; `git fetch --prune`; keep `main` the only local branch.
6. Before "done": update `CHANGELOG.md [Unreleased]`, README + `USING.md` for the CLI-surface change (#85),
   confirm url/env/cli coverage. Close each issue via its PR (`Closes #NN`).
7. Docs units: lint locally with `markdownlint-cli2 <files>` (uses in-repo `.markdownlint.jsonc`) +
   `lychee --config lychee.toml <files>` before push.

## Resume

Order: **#84 → #85 → (#39+#36) → #55.** All anchor-mapped in the plan. After this batch, the medium tier
(#46 / #80 / #49 / #33 / #32) and deferred items (#59 / #72 / #89 / #60 / #105) remain — re-rank before
starting. Releases are automated — see README "Versioning" (bump-version → PAT-merge → tag-release).
