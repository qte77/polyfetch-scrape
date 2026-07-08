# Handoff — 005 · #118 console / network-failure capture on `Response`

**Plan:** `docs/plans/005-render-console-network-capture.md` · **Status:** planned, not started ·
**Repo:** `main` (Python CI live — `Test / ci` gates every PR).
**Maintainer decisions locked:** capture **both** network signals (`requestfailed` + HTTP `≥400`);
**full** doc set; **library-only** (no CLI flag — `--json` surfacing is #105).

## Onboard

One **small, self-contained** unit. **Read the plan's "Source map" table first** — it names every file,
the exact line anchors, the verbatim code to add, and the 3 tests to write, so you execute with `grep`,
not a fresh Explore pass. Don't re-map the codebase.

- **What:** opt-in `RenderOptions(capture_console=…, capture_network_failures=…)` → collected on
  `Response.console_errors` / `Response.network_failures`. Off by default (backward-compatible; zero
  overhead unless asked). Wiring lives in `playwright_backend._attempt_once` via a new `_attach_capture`
  helper + two `_record_*` filters (registered right after `page = context.new_page()`, before `goto`).
- **The one gotcha:** carry the AGENT_LEARNINGS #3 **runner-network caveat** into the `Response` docstring
  and the `_attach_capture` docstring — a headless capture reflects only *this* process's network, so a
  cross-origin failure a real user hits can read clean.
- **Typing:** annotate the sinks `list[dict[str, object]]` so appended dict literals get expected-type
  context (dodges pyright dict-invariance under strict).

## How to handle (this repo's policy)

1. **Branch** `feat/render-capture`; topical commits by concern (core: render_options+response+backend /
   docs).
2. **Strict TDD, red first** — write the 3 capture tests (plan §"Strict TDD") and watch them fail before
   implementing. Non-trivial only: the wiring + filter + opt-in-gating tests are the point; no coverage
   padding. Keep `_attempt_once` under complexity 15 (filters live in `_record_*`).
3. `make validate` **and** `make ci` green **before** pushing. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`.
4. **Security:** run `/security-review` on the diff (expected clean — listeners collecting strings/dicts,
   no new sink); confirm the runner-network caveat is documented.
5. **Docs (full set, lockstep):** `docs/api-reference.md` (RenderOptions + Response + caveat),
   `CHANGELOG.md ### Added`, `docs/architecture.md` (render row), `docs/roadmap.md` (browser-depth facet),
   `docs/userstory.md` (JS-render story line). Lint locally: `markdownlint-cli2 <files>` +
   `lychee --config lychee.toml <files>`.
6. Open a PR (`Closes #118`); **squash-merge ONLY when all CI checks pass — never `--admin`**;
   `--delete-branch`; `git fetch --prune`; keep `main` the only local branch.

## Resume — what comes after #118 (render/crawl backlog, ROI × feasibility ranked)

Sequence the render cluster by dependency; #33 is an independent parallel track (disjoint files).

- **#117** — `render_session` managed multi-step Page (the foundation; **reuses this unit's capture**).
  Bigger surface; do next in the cluster.
- **#119** — multiple/named screenshots (lands with #117's `.shot()` + a `RenderOptions(screenshots=[…])`
  list); then **#105** — base64 screenshot in `--json` (surfaces #119's output).
- **#33** — sitemap.xml helper (standalone crawl utility; already spec'd: `defusedxml` + sitemap-index
  recursion + depth cap + gzip + `fetch()` seam). No conflict with the render work.
- **Decisions:** **#120** — close as superseded by #117 (self-described interim). **#59** — revisit only a
  CI-testable *detection* slice (raise a typed `ChallengeBlock`) once this unit lands; the headed takeover
  stays deferred. **#89** spike-gate; **#60 / #72** deferred (UI, out of core scope).
- **Tidy:** convert `--browser` to a `StrEnum` (drops its remaining `# type: ignore`) — fold into any
  `cli.py` touch.

Releases are automated — see README "Versioning" (bump-version → PAT-merge → tag-release).
