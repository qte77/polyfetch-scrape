# Handoff — 008 · Post-v0.7.0 high-ROI enhancements

## Onboard

Full plan + code/file/source map: **[`docs/plans/008-post-v070-enhancements.md`](../plans/008-post-v070-enhancements.md)**
— read it; it has the anchors so you don't re-explore. Repo clean on `main` @ `dfbba22`; nothing
started. **v0.7.0 is shipped** (tagged + released) — this is the deferred backlog from the post-release
review.

**One-paragraph why:** the 007 cycle shipped the full positioning/rename/emulation-video work as
v0.7.0. Four high-ROI items were deferred: (1) a weekly browser-tier e2e, (2) re-enabling `full_page`
screenshots if patchright 1.61.2 fixed the 0-byte bug, (3) the estate-contract follow-through (a
"consuming across the estate" doc + the deferred `#144` helper), (4) badge templating across the
estate. Plus two operational wins: self-signing release commits and fixing the Actions allow-list reset.

**Load-bearing correction (already verified this session):** **item 1 is already done** —
`.github/workflows/canonical-probe.yaml:36-40` already runs `make setup_browsers` + `make test_e2e`
weekly, so the browser tier (incl. the new emulation/video e2e guard) is already covered. Don't rebuild
it; verify-only.

## How to handle (this repo's policy)

- Everything via `make`/`uv run` (never bare pip/pytest/ruff/pyright/polyfetch); `make validate` green
  before "done"; scriv fragment per non-trivial change (`make changelog_new`).
- Git: branch per concern, topical commits, squash-merge on green CI, delete branch.
  `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN` (App token lacks repo scope; OAuth login has it). Same
  unset for `git push` (OAuth credential helper).
- **`main` enforces signed commits (ruleset).** Your OAuth `git commit` auto-signs (works). The one
  place it bites: the release bump branch is bot-authored + unsigned → the release PR is BLOCKED until
  re-signed: `git checkout -B bump-N-main origin/bump-N-main; git commit --amend --no-edit
  --reset-author; git push --force-with-lease` (the `--reset-author` is REQUIRED — the signer rejects
  author `bump-my-version`).
- **CodeQL is a required check** — never `"<url>" in x` (even in test asserts; use `==`).
- **`docs/plans/` + `docs/handoffs/` are markdownlint-linted in CI** — author these lint-clean from the
  start (blank lines around every heading/table/code-fence; ≤ header-column-count table rows; no blank
  line inside a blockquote). The 007 plan needed a 15-error cleanup because it wasn't.
- **Actions allow-list self-emptied once** → `lint / markdown` `startup_failure`. If that recurs,
  re-apply (root cause may be an org-level policy — see plan op2):

  ```bash
  env -u GH_TOKEN -u GITHUB_TOKEN gh api --method PUT \
    repos/qte77/polyfetch-scrape/actions/permissions/selected-actions \
    -F github_owned_allowed=true -F verified_allowed=true \
    -f 'patterns_allowed[]=astral-sh/setup-uv@*' \
    -f 'patterns_allowed[]=callowayproject/bump-my-version@*' \
    -f 'patterns_allowed[]=DavidAnson/markdownlint-cli2-action@*' \
    -f 'patterns_allowed[]=lycheeverse/lychee-action@*'
  ```

## Sequence (do in order)

1. **3a — estate doc** (low effort, high value, no prerequisite): new `docs/estate.md` + README/architecture
   links; reuse the env-borrow contract in `USING.md` + the ownership line in `architecture.md`.
2. **op1 — self-signing release commits** — the highest-leverage operational fix (kills the per-release
   re-sign toil). **Blocked on you:** create a bot GPG key + `GPG_PRIVATE_KEY`/`GPG_PASSPHRASE` secrets,
   then wire `bump-version.yaml:66-88` (+ whitelist/SHA-pin the import-gpg action).
3. **2 — `#132` full_page** — re-probe `page.screenshot(full_page=True)` under 1.61.2 FIRST; build the
   `capture_screenshot`/`Screenshot`/`--screenshot` support only if it writes non-zero bytes, else just
   date-stamp the "still broken" doc note.
4. **op2 — org-level Actions policy** — investigate the allow-list reset root cause.
5. Verify-only: item 1 (canonical-probe already runs e2e); 3c (decidable-line/no-pydantic already in
   `architecture.md`). Defer: `#144` (AHA), item 4 (cross-repo).

## Open decisions (recommendations in the plan)

- `#144` ui-check helper: **defer** (AHA — not ≥2 repos + stable API yet).
- `full_page`: **build only if** the 1.61.2 re-probe shows non-zero bytes.
- op1 signing: **option A (bot GPG key)** recommended over the action-free graphql path; needs your secret.

## State at handoff (2026-07-16, `main` @ dfbba22, v0.7.0 released)

- Merged this cycle (post-007): #157 #158 #139 #159 #160 #161 #162 #163 #165 #166 #169(release) #168
  #170 #171 #172 #173 #174. v0.7.0 tagged + GitHub Release published.
- Closed: #60 #89 #146 #148 #154 #155 #122 #125. Opened: **#164** (pydantic tracking — intentional,
  open-question). Backlog untouched: #132 (this plan) #144 #147 #59 #153.
- Actions hardened (selected + SHA-pinning + the 4-action allow-list). One pending scriv fragment
  (`refresh_e2e_targets`) → next release. Nothing on branches; no WIP.
