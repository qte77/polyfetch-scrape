# 010 — Issue triage → parallel worktree lanes (post-v0.8.0)

**Status (2026-09-29):** Phase A started. Lanes **L1 (#181), L2 (#199, #216) and L3 (#197)** launched in parallel worktrees from `main` @ `01cef56`. The source-map line numbers are from `f689c3c` (v0.8.0); the plan merge `01cef56` didn't touch `src/`, so they still hold. An independent (Fable) review changed the protocol: lanes never edit this plan, and the orchestrator strikes rows. Its findings are folded in below.

## Start here (handoff)

You are the **orchestrator**. You read this plan, launch **lane subagents in parallel, each in its own git worktree**, review their PRs, and merge them **one at a time**. You do not write lane code yourself.

1. **Sync.** `git -C <repo> fetch origin --prune`. Read the [remaining-work table](#remaining-work) (the only list of open work) and `gh pr list` / `gh issue list` (commands below). Anything merged since 2026-09-29 is struck in the table; if not, strike it first.
2. **Pre-flight (every time, before spawning):**
   - `df -h /workspaces`: needs **≥ 400 MB free** for up to 3 worktrees. Each worktree `.venv` goes on `/tmp` (see [Worktree protocol](#worktree-protocol)). Never let a lane create `.venv` inside the worktree: `/workspaces` sat at 98% (812 MB free) on 2026-09-29, and one `.venv` is 291 MB.
   - The main checkout may be on the parked WIP branch `feat/009-wave2-render-input-surface`. **Worktrees must not inherit it.** Every lane's first command resets its branch onto `origin/main`.
3. **Spawn ≤ 3 lanes in parallel** (one message, several `Agent` calls, each with `isolation: "worktree"` and `name: "lane-Lx"`, so you can `SendMessage` them later). Use the [lane prompt template](#lane-prompt-template). The first batch was **L1, L2 and L3**. As slots free up, the order is **L6 (#212)** next (a lockfile bump; everything else rebases onto it once), then **L5**, then **L4**. L4's #198 waits until #229 has merged, because both add a field to `response.py` and to the `--json` output.
4. **Merge loop (orchestrator only, serial):**
   - When a lane reports "PR #N green", check that `gh pr checks N` passes (ci, Analyze/CodeQL, lint/markdown, lint/links, CodeFactor).
   - **Strike the row yourself.** Check out the PR branch, commit a signed `docs(plans): strike #N` edit to the [remaining-work table](#remaining-work), push, and wait for the checks again. That keeps the rule "strike in the same PR" without lanes ever conflicting on adjacent rows. **Lanes never edit this file.**
   - `gh pr merge N --admin --squash --delete-branch`. The owner authorized `--admin` on 2026-09-24. **Never modify rulesets.**
   - Message every still-open lane (`SendMessage` to `lane-Lx`) to `git fetch origin && git rebase origin/main`, re-run `make validate`, then `git push --force-with-lease`.
5. **Per merged PR:** close its issue if `Closes #N` didn't. Delete the remote and local branch. Clean up the worktree (`git worktree unlock <path>`, then `git worktree remove <path>`, `git worktree prune`; harness worktrees are **locked**). Run `rm -rf /tmp/pf-venv-<lane>`. Update memory. After **#181** merges: cut **v0.8.1** (security fix) and open the DNS-rebinding follow-up issue from the draft in the PR body.
6. **Stop and ask the owner** only at 🔒 gates (Phase B). Everything else has a recommended default: apply it.

**Owner-gated (Phase B), do not start without an answer:** see [Decisions](#phase-b--owner-decisions-with-defaults).

## Worktree protocol

The Agent tool's `isolation: "worktree"` creates `.claude/worktrees/agent-<id>/` on its own branch. It's gitignored as of this plan's PR. Inside the worktree, the lane's **first commands**, run one per Bash call (compound commands are often denied):

```bash
git fetch origin
git switch -C <lane-branch> origin/main      # NEVER build on the checkout's HEAD (may be the WIP branch)
export UV_PROJECT_ENVIRONMENT=/tmp/pf-venv-<lane>   # venv off the full /workspaces volume
uv sync --frozen
make validate                                  # baseline must pass before any edit
```

- `UV_PROJECT_ENVIRONMENT` must be set in **every** Bash call that runs `uv` / `make` (shell state doesn't persist). Prefix it: `UV_PROJECT_ENVIRONMENT=/tmp/pf-venv-<lane> make validate`. Check `echo $UV_CACHE_DIR` shows `/tmp/uv-cache` (the profile sets it). If it's empty, also prefix `UV_CACHE_DIR=/tmp/uv-cache`, because `$HOME` (`~/.cache`) is on a ~97%-full volume too.
- **GitHub API calls:** `api.github.com` TLS timeouts happened repeatedly on 2026-09-29. Wrap every call as `timeout 90 env -u GH_TOKEN -u GITHUB_TOKEN gh …`, retry up to 3× with a pause, and poll `gh pr checks N` (~60 s) instead of `--watch`. Confirm pushes with `git ls-remote origin <branch>`.
- **CPU:** parallel `make validate` runs plus Patchright e2e contend for CPU. Rerun a timed-out e2e once on its own before calling it a failure.
- The Patchright Chromium lives in the shared `~/.cache/ms-playwright`, so no per-worktree browser install is needed. Run `make doctor` if an e2e says Chromium is missing.
- Temp files go in `<worktree>/.scratch/` (gitignored), never the repo root.
- On finish, the orchestrator removes the worktree (`git worktree unlock <path>`, then `git worktree remove <path>` and `git worktree prune`; harness worktrees are created **locked**) and runs `rm -rf /tmp/pf-venv-<lane>`.

## Lanes (parallel-safe split)

A lane is one subagent in one worktree. It works through its items in order, **one PR per issue**, and each PR is based on the latest `origin/main`. The file ownership below is what makes lanes parallel-safe.

| Lane | Items (in order) | Owns these files (others must not edit) | Shared hotspots (rebase before merge) |
|---|---|---|---|
| **L1 security** | #181 (the orchestrator opens the follow-up issue after merge) | `utils/_ssrf.py`, new `tests/utils/test_ssrf.py`, **new root `tests/conftest.py`** (an autouse `socket.getaddrinfo` stub; once `check_ssrf` resolves, existing discovery/sitemap/easter_hunt tests would otherwise hit real DNS), the "literal-IP only" docstrings (`utils/_ssrf.py:4-6`, `contrib/easter_hunt/orchestrator.py:6-8`, `utils/discovery.py:63`), and `docs/architecture.md:59,60,79` | `tests/conftest.py` becomes shared from then on |
| **L2 render lifecycle** | #199 → #216 → #229 | `render_session.py`, `_backends/patchright_backend.py` (`context_kwargs`, `_finalize_video`), `render_options.py` | `response.py`, `cli.py` `--video-out`/`--har-out` block, `USING.md`, `docs/api-reference.md` |
| **L3 platform** | #197 | new `src/polyfetch_scrape/_platform.py`, `cli.py` `doctor` block (`:477-535`) | `README.md` install note |
| **L4 CLI + httpx** | #214 → #198 (#198 only after #229 has merged) | `cli.py` `fetch_cmd` body flags (`:181-321`), `utils/http_ua.py`, `_backends/httpx_backend.py` | `response.py` (if #198 adds a field), `USING.md` |
| **L5 errors** | #209 | `_backends/__init__.py` (`FingerprintBlock`), `errors.py`, the three `raise FingerprintBlock` sites | `docs/api-reference.md` Exceptions |
| **L6 deps** | #212 (Dependabot, `ci` red) → #222 once it rebases | `uv.lock`, `.github/workflows/*` | none (merge L6 alone, then rebase the others) |

Each lane must stay inside its owned files. If an item needs a file another lane owns, stop and report instead of editing it. Changelog fragments are per-PR files (`changelog.d/<ts>_<slug>.md`), so they never conflict. **No lane edits this plan file**; the orchestrator strikes rows. Other known shared spots that rebases must preserve:
- the `cli.py` import block (L2 #229, L3 #197, L4 #214 all add imports; never reorder or reformat it);
- `tests/test_cli.py`;
- `response.py`, `cli.py:346-349` and `USING.md:88-100` (L2 #229 `har_path` vs L4 #198 `request_user_agent`, hence the ordering above).

### Lane prompt template

```text
You are lane <Lx> of docs/plans/010-issue-triage-parallel-lanes.md in qte77/polyfetch-scrape.
You run in a git worktree. FIRST: follow the plan's "Worktree protocol" exactly (git switch -C <branch> origin/main;
UV_PROJECT_ENVIRONMENT=/tmp/pf-venv-<lx>; make validate baseline).
Items, in order, one PR each: <items>. Read each issue (gh issue view N --comments) and the plan's source-map rows.
Only edit files your lane owns (plan § Lanes). TDD: write the failing test first, then the fix.
Per PR: make validate green; markdownlint-cli2 + lychee --config lychee.toml on changed md; changelog fragment
(make changelog_new, NO relative links in fragments); do NOT edit docs/plans/010 (the orchestrator strikes rows);
commits split by topic, Conventional Commits, signed (verify with /usr/bin/git log --format=%G?);
push with env -u GH_TOKEN -u GITHUB_TOKEN (sandbox disabled), confirm with git ls-remote; every gh call wrapped as
timeout 90 env -u GH_TOKEN -u GITHUB_TOKEN gh ... with up to 3 retries; gh pr create with "Closes #N" and a
"Verification" section. Then poll gh pr checks N every ~60s (not --watch). Report "PR #N green" or the failing
check + log excerpt. Do NOT merge, do NOT edit rulesets, do NOT touch other lanes' files, do NOT comment on or
close contributor PRs or issues. Credit ported contributor code with a Co-authored-by trailer whose name/email is
copied from the contributor's actual fork commit (gh api repos/<fork>/commits?sha=<branch>&per_page=1), never guessed.
```

## Source map

All paths are under `src/polyfetch_scrape/`, line numbers from `origin/main` `f689c3c`. Re-grep if the base moved.

**#181 SSRF (L1).** `utils/_ssrf.py:13` `check_ssrf(url)`. `:19` parses a literal IP; non-IP hosts return at `:21` (the bypass). `:22-29` range checks, `:30` raises `ValueError`. Callers: `utils/discovery.py:67,88`, `utils/sitemap.py:56`, `contrib/easter_hunt/orchestrator.py:49`. Plain `fetch()` is **not** guarded. Tests are spread across `tests/utils/test_discovery.py:140`, `tests/utils/test_sitemap.py:122,129`, `tests/contrib/easter_hunt/test_hunt.py:172-247` and `tests/test_cli.py:696`; there's no dedicated `test_ssrf.py`.
- **Port PR #201's diff:** `gh pr diff 201`, from the fork `dntywntme/polyfetch-scrape`. It resolves A+AAAA via `getaddrinfo`, rejects if any address is internal, adds `check_redirect()` for the final URL and `permanent_redirect_to`, and dedupes the easter_hunt copy. Its CI **never ran**: fork runs waited for approval and GitHub expired them after 30 days with 0 jobs.
- **Severity: Moderate-High.** The attack path is attacker-controlled sitemap, feed or JSON-LD content fed to `discover()`/sitemap walking.
- **#201 is stale in one respect:** its easter_hunt dedupe already exists on main (`contrib/easter_hunt/orchestrator.py:19` imports `utils._ssrf`). Port the semantics, not the diff.
- **State two limits in the PR and changelog:**
  - The redirect check is **post-hoc** for curl_cffi (`curl_backend.py:74` passes no `allow_redirects`; the default follows redirects, UNVERIFIED) and Patchright (`page.goto` always follows). The internal request has already been sent when `check_redirect` refuses it. httpx doesn't follow redirects, so it's unaffected.
  - DNS rebinding is out of scope.
- **Keep plain `fetch()` unguarded.** Consumers legitimately fetch localhost (e.g. `perf-cwv-pass` drives a local serve), and `docs/architecture.md:79` puts validation at the entry point. Add an opt-in `ssrf_guard=` only when a second caller needs it (AHA).
- **Follow-up issue to open after merge:** DNS-rebinding TOCTOU and per-hop redirect checks, plus browser subresources. It needs the resolved IP pinned per tier. Candidate mechanisms, all UNVERIFIED (check vendor docs before the issue quotes them):
  - httpx: connect to the IP, with the `Host` header and the `sni_hostname` extension;
  - curl_cffi: `CURLOPT_RESOLVE`;
  - Patchright: `--host-resolver-rules`, plus a `context.route` guard.

**#199 video path (L2).** `render_session.py:132` `_teardown` closes context → browser → `pw.stop()` (`:133`), then reads `self._video.path()` at **`:141`, after the driver stopped**, which is the bug. Move the read to right after `context.close()`. The fetch path is already correct: `_backends/patchright_backend.py` `_attempt_once` `:150` context.close, then `_finalize_video` `:209` (`video.path()` `:218`). Session lifecycle: `__enter__` `:80` (`:81` start, `:82` launch, `:83` new_context, `:84` new_page, `:86` `_video`), `__exit__` `:94`. Tests: `tests/test_render_session.py:183,193`. Port PR #202's diff and test (`gh pr diff 202`).

**#216 DX (L2).** No `set_default_timeout` / `set_default_navigation_timeout` anywhere. Add both after `new_page` at `render_session.py:84`, using the session timeout (`_timeout_ms` `:59`). The viewport is typed `tuple[int, int] | None` at `render_session.py:49,150` and `render_options.py:91`, and mapped to `{width,height}` at `patchright_backend.py:111-112`. Document the tuple shape in `docs/api-reference.md:83` "Render session".

**#229 HAR (L2, after #199).** `_backends/patchright_backend.py:102` `context_kwargs(pw, opts)` builds device `:107-108`, viewport `:111`, UA `:113`, locale `:115`, color_scheme `:117`, `record_video_dir` `:119-120` and `record_video_size` `:121-125`. **Add `record_har_path` / `record_har_mode="minimal"` / `record_har_content="omit"` after `:125`.** Mirror video everywhere:
- `render_options.py:96-97` (fields, docstring `:77-80`)
- `response.py:21` (`video_path`; add `har_path`)
- `render_session.py:75,141` (`video_path`)
- `cli.py:250-256` `--video-out` (add `--har-out`), `cli.py:177` `_build_render_options`, `cli.py:346-349` JSON `video_path` (add `har_path`)

The HAR is written on `context.close()`, the same ordering as #199. Patchright 1.61.2 exposes `record_har_*` on `new_context()`. The HAR summary goes in as a recipe in `docs/scripting.md` (after `:12` "DevTools capture"), stdlib `json` only.

**#197 musl (L3).** No platform detection anywhere. `cli.py:477` `_chromium_ok` (headless launch `:487`), `:493` `_install_chromium`, `:500-501` `doctor`. Port PR #206's `_platform.py` gate and tests (`gh pr diff 206`).

**#214 CLI body (L4).** `cli.py:181-293` `fetch_cmd`: `method` `:184`, and `--json` (`json_output`, meaning *output*) at `:288`, so the new flag **must not** be `--json`; use `--json-body` / `--data` (+ `@file`). The `fetch(...)` call is at `cli.py:309-321`. `client.py:49-66` `fetch` has `headers` `:53`, `json` `:63`, `content` `:64`, a mutual-exclusion check `:68-69`, and rejects a body on the patchright tier at `:166-167`.

**#198 httpx UA (L4).** `utils/http_ua.py:27` `USER_AGENTS`, `:43` `STABLE_USER_AGENT`, `:50` `pick_user_agent` (used by no backend). `_backends/httpx_backend.py:16` imports `STABLE_USER_AGENT`. `_with_default_headers` `:101` injects the UA at `:109-110`. No `Response` field records the sent UA; recommended default: add `request_user_agent` to `response.py` and the `--json` output.

**#209 FingerprintBlock (L5).** The class is at `_backends/__init__.py:15` (not in `errors.py`). `errors.py:1` `FetchError(*args, status=None)` `:4`; subclasses at `:11,15,19`. Raise sites: `_backends/curl_backend.py:59`, `_backends/httpx_backend.py:64`, `_backends/patchright_backend.py:67`; caught at `client.py:139`. Add bounded `headers` / `body_excerpt` attributes, truncated (e.g. 2 KB) and never including request cookies.

**#212 / #222 deps (L6).** `gh pr view 212 --json statusCheckRollup`, then `gh run view <id> --log-failed` to find the red `ci` step. #222 bumps actions in `.github/workflows/bump-version.yaml`, which #226 rewrote, so it conflicts until Dependabot rebases it. Comment `@dependabot rebase` if it hasn't. **Never re-add `callowayproject/bump-my-version`.**

**Phase C anchors.**
- **#200/#178 auth sessions:** `storage_state` / `cookies` are not in `src`. The only header path is `context.set_extra_http_headers` at `patchright_backend.py:140`. Inputs: WIP `c61557f` (10 files, +393/-34, incl. #182 `capture_network`) and PR #203 (adds `extra_http_headers` + save `storage_state`, and fixes a header-clobber bug).
- **#182:** `attach_capture` `patchright_backend.py:249-265` (recorders `:229-246`, used at `:142` and `render_session.py:85`); `render_options.py:89-90`; `response.py:25-26`; `render_session.py:77-78` (forced on at `:60-61`). PR #204 is an input.
- **#190/#59 headless:** hard-coded at `patchright_backend.py:51`, `render_session.py:82`, `cli.py:487`.
- **#147 robots:** reuse `utils/discovery.py:122` `_robots_sitemaps`, which already fetches `/robots.txt` at `:123`; also `_fetch` `:86`, `discover` `:59`.
- **#230 perf:** Patchright exposes `browser.start_tracing()` / `stop_tracing()`.

**Docs anchors.**
- `USING.md`: `:27` DevTools capture, `:66` Commands (fetch flag prose `:78-82`), `:88` Output schema (`video_path` `:100`).
- `docs/api-reference.md`: `:41` Render controls, `:83` Render session, `:104` Response, `:125` Exceptions, `:152` CLI-only commands.
- `docs/architecture.md:46` component table (`patchright_backend` `:55`, response `:56`, render_options `:57`, render_session `:58`, cli `:63`).
- `docs/scripting.md:12` DevTools capture.

**Tests / tooling.**
- Unit tests under `tests/` (one file per module).
- e2e: marker `e2e` (`pyproject.toml:47`, excluded by default at `:44`), in `tests/test_e2e.py`.
- Makefile: `validate` `:55`, `ci` `:63`, `test_e2e` `:49`, `audit` `:43`, `changelog_new` `:80`, `doctor` `:20`.

## Phase B — owner decisions (with defaults)

Defaults apply unattended except where marked 🔒 (the agent must wait).

| # | Decision | Default |
|---|---|---|
| D1 | Contributor PRs #201/#202/#203/#204/#206: port into our branches (with `Co-authored-by`) or ask the author to rebase? | **Port**, then close theirs with thanks + a link (the closing is 🔒 owner) |
| D2 | 🔒 Auth-session lineage: build #200 on WIP `c61557f` or on PR #203? | WIP as the base, cherry-picking #203's header-clobber fix + `extra_http_headers` |
| D3 | 🔒 #228 bare proxy passthrough in scope? | Defer: one consumer; README excludes proxy *rotation* |
| D4 | #59 engine or recipe? | Engine, after #190 |
| D5 | 🔒 #183 crash semantics | No auto-relaunch; surface the page crash as a typed error |
| D6 | 🔒 #218: edit or hide the two #190 comments | Owner edits their own; hide the external one |
| D7 | 🔒 Close #205, #207 (superseded by #219/#221), #127 (decided recipe), #211 (not a build request) | Close with a comment |
| D8 | 🔒 #230: engine `capture_performance` or trace recipe | Trace recipe + a real-browser spike first |
| D9 | 🔒 Remove the unused `callowayproject/bump-my-version@*` from the Actions allow-list | Remove. That also makes any stale re-add (e.g. an old Dependabot #222) fail when the workflow is parsed |
| D10 | 🔒 Community: before each port lands, post a one-line heads-up on #201/#202/#206 ("landing as #N with you as co-author")? Invite `dntywntme` as a collaborator, which removes the fork-run approval/expiry problem at the root? | Heads-up: yes (the orchestrator posts it once you approve). Invite: your call |

## Remaining work

The **only** list of open work. Strike a row (`~~…~~ ✅ #PR`) in the PR that ships it. Gate: `agent` (lane may run), `owner` (🔒 decision first), `data` (waits on an external signal). ROI 1–5; effort S (<½ day), M (1–2 days), L (>2 days).

| # | Item | Lane / phase | Gate | ROI | Effort | Done when |
|---|---|---|---|---|---|---|
| ~~181~~ | ~~SSRF: resolve DNS names, check all addresses + redirects (port #201)~~ ✅ #233 (now a public-only allowlist: `not is_global or is_multicast`, which also closes 100.64.0.0/10 / Alibaba metadata) | L1 / A | agent | 5 | S | Unit tests: a name resolving to 127.0.0.1 / 169.254.169.254 / ::1 / 10.x (or mixed) is rejected, and a public name passes. `make test` stays offline (root `conftest.py` stubs `getaddrinfo`). The literal-IP docstrings and architecture lines are updated. The post-hoc-redirect and rebinding limits are stated in the PR and changelog. `fetch()` is left unguarded |
| 199 | `render_session` reads `video_path` before the driver stops (port #202) | L2 / A | agent | 4 | S | Unit test asserts the path is read before `pw.stop()`; e2e `render_session(record_video_dir=…)` yields an existing `.webm` |
| 216 | `render_session` default timeouts + viewport shape documented | L2 / A | agent | 3 | S | Unit test: `set_default_timeout` / `set_default_navigation_timeout` called with the session timeout; api-reference documents `(w, h)` |
| 229 | Opt-in HAR recording + summary recipe | L2 / A (after 199) | agent | 4 | M | e2e writes a valid HAR 1.2 with the document entry; `har_path` on Response and in `--json`; `--har-out`; secrets warning in docs |
| ~~197~~ | ~~Detect musl, fail loudly in `doctor` / browser tier (port #206)~~ ✅ #234 | L3 / A | agent | 4 | S | Shipped. Known limit: patchright is a hard dependency, so `uv sync` on musl still fails at resolution (making it an optional extra is a separate decision) |
| 214 | CLI request body `--json-body` / `--data` | L4 / A | agent | 4 | S | CLI tests: the body reaches `fetch(json=…)` / `content=`; both at once → exit 2; patchright tier → clear error |
| 198 | Surface the httpx-tier UA (`request_user_agent`) | L4 / A (after 214) | agent | 3 | S | Response + `--json` carry the sent UA; USING documents the default |
| 209 | `FingerprintBlock` carries bounded headers / body excerpt | L5 / A | agent | 3 | S–M | Tests at all three raise sites; excerpt ≤ 2 KB; no cookies |
| 212 | Dependabot python-deps: fix the red `ci` | L6 / A | agent | 3 | S | `ci` passes; merged or closed with the reason |
| 222 | Dependabot actions group (after rebase) | L6 / A | data | 2 | S | Rebased onto #226; no `callowayproject` action re-added; passes; merged |
| 200 | Authenticated sessions (storage_state, headers); absorbs #178 core | C | owner (D2) | 4 | M | Save + resume round-trip e2e; persistent-profile sub-ask split into a new issue |
| 182 | Opt-in full network log (+SSE via CDP) | C (after 200) | owner (D2) | 3 | M | Per-request list on Response / RenderSession; e2e |
| 190 | Launch option: headed-under-xvfb / mobile mode | C | agent | 4 | M | Option threads through all three headless sites; e2e on a benign page |
| 179 | Automation-fingerprint diagnostic report | C | agent | 3 | M | Read-only report; no spoofing |
| 147 | Opt-in robots.txt helper (reuse `_robots_sitemaps`) | C | agent | 3 | M | Allow/deny per UA, unit-tested; #153 checklist updated |
| 59 | Headed manual-takeover handoff | C (after 190) | owner (D4) | 3 | L | Per the D4 outcome |
| 230 | Performance capture | C | owner (D8) | 3 | M | Spike findings recorded; then the recipe or opt-in lands |
| 183 | Chromium crash under load | C | owner (D5) | 3 | L | Crash surfaces as a typed error; repro notes |
| 228 | Proxy passthrough | C | owner (D3) | 2 | S | Per D3 |
| 144 | Shared ui-check helper | later | data | 3 | L | ≥2 consumers agree on a stable API (AHA) |
| 153 | Tracking: structured-first | tracker | — | — | — | Closes when #147 ships |
| 218 | Third-party mentions on #190 | B | owner (D6) | 2 | S | Comments edited or hidden |
| 205, 207, 127, 211 | Close as superseded / decided / not planned | B | owner (D7) | — | S | Closed with a comment |
| — | Actions allow-list cleanup | B | owner (D9) | 1 | S | Pattern removed |
| — | Release **v0.8.1** (security) right after #181 merges | A | agent | 4 | S | Bump workflow `patch`; close and reopen the bump PR so CI runs; admin-squash; the Tag and Release run succeeds and the release is marked Latest |
| — | DNS-rebinding / per-hop / subresource follow-up issue | A (after 181) | agent | — | S | Issue opened from the #181 PR-body draft, with the vendor mechanisms verified or marked UNVERIFIED |
| — | `SECURITY.md` (reporting path + SSRF-guard scope) | A | agent | 3 | S | File exists, linked from README; states what `check_ssrf` guards and what it doesn't |
| — | Heads-up comments on contributor PRs; close them after porting | B | owner (D1, D10) | 2 | S | Comment posted before each port merges; PRs closed after merge per D1 |
| — | Release **v0.9.0** at the end of Phase A (#229 is a feature) | A (end) | agent | 3 | S | All Phase A rows struck; bump `minor`; released as above |

## Watch-outs

- **gh / git:** every `gh` and `git push` runs as `env -u GH_TOKEN -u GITHUB_TOKEN …` with the sandbox disabled. A stale token gives a 401, and a sandboxed push can silently no-op. Verify with `git ls-remote`.
- **Signed commits:** the `main` ruleset requires them. Local commits are signed by the Codespace signer, which can time out: retry, and check `/usr/bin/git log --format='%h %G?'` shows `E`/`G`, not `N`.
- **The RTK hook rewrites `git` output.** Use `/usr/bin/git` when output is parsed. Compound Bash commands (`&&`, pipes) are often denied: one command per call.
- **CodeQL fails on `"<url>" in x`**, even in tests. Use `==`.
- **Scriv fragments must not contain relative links**: lychee resolves them against `changelog.d/`.
- **Contributor PRs are forks.** Their Actions runs need maintainer approval, and GitHub expires them after 30 days. Porting the diff into our own branch is what gets it tested.
- **Releases:**
  - Run the Bump version workflow (`uvx bump-my-version`, #226).
  - Close and reopen the bump PR with your own token so CI runs.
  - Admin-squash it; Tag and Release then fires.
  - Test workflow changes with `gh workflow run … --ref <branch>`.
- **Disk:** `/workspaces` is nearly full. Keep venvs on `/tmp` and remove finished worktrees promptly.
- **Headless capture reflects this runner's network only**, and Patchright's `evaluate` runs in an isolated world (AGENT_LEARNINGS.md).

## Context: how this arc was derived

The 009 arc (the v0.8.0 delta: #219–#227, including the release-pipeline fix #226) shipped without a plan file; its record is `CHANGELOG.md` [0.8.0]. This plan comes from a 2026-09-29 triage: three parallel subagents scored all open issues for ROI × feasibility, with an extra pass over DevTools 152. That pass found nothing to adopt: Patchright 1.61 bundles Chromium 149, and the useful item (web-vitals v6) belongs to the estate `perf-cwv-pass` skill. #229 and #230 were opened from that pass.
