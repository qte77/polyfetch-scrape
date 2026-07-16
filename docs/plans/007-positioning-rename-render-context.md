# 007 — Positioning + `patchright` rename + emulation/video → core RenderOptions

> **Status: SHIPPED in v0.7.0 (2026-07-16).** Historical planning record. **One deviation:** the
> `playwright`→`patchright` tier rename shipped as a **hard break with no deprecated alias** (this
> plan proposed keeping a deprecated `"playwright"` alias). See `CHANGELOG.md` for the shipped surface.
>
> Line numbers are as of `main` @ `6132e38`; re-grep to confirm before editing. This plan is
> self-contained — the **Source map** sections mean the next session need not re-explore.

## Context

Outcome of a long positioning/USP discussion + a fresh ROI×feasibility triage of our open issues.
Goal: (1) make polyfetch's value proposition clear and neutral, structured around **two layers**
(core `fetch()` engine vs. scripting substrate); (2) fix the **Patchright≠Playwright** naming; (3) build
the emulation/video knobs consumers keep asking for. Nothing started — repo clean on `main`.

**Key finding (load-bearing):** `new_context()`-time options — device presets, viewport, `color_scheme`,
`user_agent`, `locale`, `record_video_dir` — **cannot** be applied through the `render_session().page`
escape hatch (the context is already built bare). Only *post-context* ops (clicks, screenshots,
`set_viewport_size`, `aria_snapshot`) are scriptable. So emulation+video **must** be core `RenderOptions`
(not "just script it"). This is the precise engine/scripts line: **new_context-time = engine; post-context = scripts.**

## Prioritized roadmap (our issues; Dependabot #139 excluded)

| Cluster / issue | ROI | Feas | Verdict |
|---|---|---|---|
| Emulation+video → core RenderOptions (#148 #154 #155 #125 #122) | H | H | **Wave 2** build |
| #105 screenshot_b64 in `--json` (plan-006 exists) | M | H | **Wave 0** — unblocks Dependabot #139 (patchright 1.61.2) |
| #146 doc venv-borrow · #145 doctor/ensure-chromium | H | H | **Wave 0** (146 likely subsumed by PR B) |
| Positioning + `patchright` rename | H | H | **Wave 1** |
| #132 re-verify `full_page` | M | H | Wave 3 (cheap) |
| #127 a11y capture | M | H | **scripted `.page` recipe**, not core |
| #144 ui-check helper | M | M | backlog (AHA, API unstable) |
| #147 robots · #59 captcha handoff | M | M | backlog (#153; niche) |
| #89 USPTO · #60 UI | L | spike | spike→close (downstream) · close #60 (off-thesis) |

Order: #105/006 → #139 merges (patchright 1.61.2) → Wave-1 rename → Wave-2 emulation (on renamed code + newer patchright).

---

## Wave 0 — cheap wins + unblock

- **#105** — execute the existing **`docs/plans/006-cli-json-screenshot.md`** (base64 `screenshot_b64` in `fetch --json`; it also extracts `_run_pool` from `bulk` → fixes the complexipy breach → **unblocks Dependabot #139** patchright 1.61.2). Watch the `cli.py` collision with PR A's `_TierChoice` — sequence + rebase.
- **#145** — `doctor` / ensure-chromium. **Source map:** command template = `bulk` at `cli.py:217` (`@app.command()`) — add `doctor` alongside it; the install command it wraps = `Makefile:17` `setup_browsers` (`uv run patchright install chromium`). **Steps:** (1) `polyfetch doctor` (or `make doctor`) probes whether Chromium is installed (e.g. attempt a headless launch or check the patchright cache dir); (2) if missing, run/echo the install; (3) exit non-zero when unhealthy. Network-free unit test via the CLI-fake pattern (`tests/test_cli.py`). Own PR + `### Added` fragment + CONTRIBUTING make-table row.
- **#146** — document the `uv run --directory` venv-borrow contract in **README** (already in `USING.md`; #146 wants a README pointer). **Folds into PR B** (Script-author nav).

## Wave 1 · PR A — rename `playwright` tier → `patchright`  (`refactor/rename-patchright-tier`)

Breaking-ish (pre-1.0). Keep `"playwright"` as a **deprecated input alias** (map→`patchright` + `DeprecationWarning`) — live sibling consumers pass `--tier playwright`.

### Source map (label = the string `"playwright"`)

- `src/polyfetch_scrape/response.py:13` — `backend: Literal["httpx","curl_cffi","playwright"]` → `…,"patchright"]`. **The one unavoidable break:** `Response.backend` now returns `"patchright"`.
- `src/polyfetch_scrape/client.py:29` `Tier = Literal[...]`; `:42` `_TIER_ORDER`; `:114` `hi: Tier = … "playwright"`. Dispatch `_run_chain`→`_dispatch` (~:120-168) calls `playwright_backend.attempt(...)` at `:168`.
- `src/polyfetch_scrape/cli.py:20-34` `_TierChoice(StrEnum)` (`:29` `playwright="playwright"`) + `_as_tier` (`:31-33`, `cast` to `Tier`).
- `src/polyfetch_scrape/_backends/playwright_backend.py:108` — `backend="playwright"` in the Response build.
- Module refs to rename: file `_backends/playwright_backend.py` → `patchright_backend.py`; importers `client.py`, `render_session.py:23` (`from …_backends.playwright_backend import attach_capture, capture_screenshot`), tests below.
- Tests w/ the label (flip to `"patchright"`): `tests/test_cli.py:90,147,152,220,233`; `tests/test_client.py:292,323,378,384,386,434,439,476,496,501,518,540,542,571`; `tests/test_e2e.py:95,135`; `tests/test_playwright_backend.py:78` (rename file → `test_patchright_backend.py`).

### Design (PR A)

- Add `_normalize_tier(t)` in `client.py`: if `t=="playwright"` → `warnings.warn(DeprecationWarning("tier 'playwright' renamed to 'patchright'; alias removed in a future release"))` and return `"patchright"`. Apply to `tier`/`min_tier`/`max_tier` in `fetch()`. `Tier` Literal = `…"patchright"` only (typed callers passing `"playwright"` get a pyright nudge but runtime still works via the normalizer).
- CLI: `_TierChoice` add `patchright="patchright"`, keep `playwright="playwright"`; `_as_tier` routes both through the normalizer.
- **Gotcha:** `pyproject.toml:44` `filterwarnings=["error"]` → the alias test MUST use `with pytest.warns(DeprecationWarning):`; ensure default paths emit nothing.
- Add `tests/…::test_playwright_tier_alias_deprecated` (passes `tier="playwright"` → works, warns, `resp.backend=="patchright"`).
- Mechanical doc swaps `--tier playwright`→`--tier patchright` + Literals: `README.md:63,65`, `docs/api-reference.md:13,15,45,60,84 …`, `USING.md:33`. scriv `### Changed` (breaking; note `Response.backend` value change + deprecated alias).

---

## Wave 1 · PR B — two-layer positioning docs  (`docs/positioning-two-layer`, on PR A)

No code. Tone: **neutral** (drop "hostile"/"the moat"); sharpen value, no moat claims (distillation: no moat exists).

### Source map + edits

- **`README.md`**: hero `:3` → value-first two-layer line (engine + scripting substrate). Add **`## Core engine vs. scripts`** spine section (engine = supported/stable `fetch()`; scripts = drive the installed instrumented stealth-Patchright `Page` via `render_session()`+`.page`+env-borrow — **example scripts, not core**). Add **`## How it compares`** table (vs httpx/requests, curl_cffi/cloudscraper/undetected-chromedriver, raw Playwright/Patchright, hosted scrapers — neutral). Add **`## What it does not do`** — two buckets: *out of scope* (proxy/residential rotation, LLM/markdown extraction, hosted service) vs *scriptable on `.page` today* (a11y `aria_snapshot`, multi-step walks, screenshots — **NOT emulation/video**, those are core). Neutralize `:16` "Beats blocks a UA swap can't". Add "Script author" to the "I am a" nav `:24`.
- **`docs/architecture.md`**: above the component table (`~:38-50`) add the two-layer framing + public/private boundary (`fetch, Response, RenderOptions, render_session, RetryPolicy, Throttle, FetchError`+subs public; `_backends/` private; `contrib/` unsupported). Extend Invariants (`:52-65`) with the **boundaries/ownership/I-O/separation** block incl. the **no-pydantic/no-pydantic-settings** decision (frozen+slots dataclass value objects = outputs/config not input-validation boundaries; explicit-param config, **no env/global settings** — a library not an app; untrusted input handled at the parse boundary — `defusedxml`+regex/`json`+the shared `utils/_ssrf.py` guard). Note the technical engine/scripts line + Patchright≠Playwright in the backend row (`:43`). Link the pydantic tracking issue.
- **`pyproject.toml:4`** description + **repo About** (`gh repo edit`) → neutral value line.
- **`docs/roadmap.md:62`** drop "horizontal, **hostile-fetch**"; **`:72`** drop "(**the moat**)".
- **`docs/userstory.md`** → label **engine-user** vs **script-author** personas.
- **`USING.md`** (script-author landing) → lead with the substrate + a `.page` recipe: `s.page.locator("body").aria_snapshot()` (Patchright 1.58.2 API; `page.accessibility.snapshot()` removed upstream PW 1.57).
- **`docs/scraping-landscape.md`** → keep the Patchright detail (`:60-63`); cross-link the README compare. **`docs/show-hn.md`** → align two-bucket + patchright if trivial.
- scriv `### Changed` (README-surface restructuring).

---

## Wave 2 — emulation + video → core `RenderOptions`  (`feat/render-context-options`)

Resolves #148/#154/#155 (emulation) + #125/#122/#155 (video). Consumers (sfclarity, azure-doc-workflows, fo-scraper, ajoa-kit) hit this in GUI e2e today.

### Source map

- Two bare `new_context()` sites: `_backends/patchright_backend.py:75` (in `_attempt_once`; `pw` is in scope in `attempt()` `:46-47` `with sync_playwright() as pw`), and `render_session.py:54` (`__enter__`).
- `render_options.py:42-69` `RenderOptions` (frozen/slots; fields end `:69` `capture_network_failures`). Add: `viewport: tuple[int,int]|None`, `device: str|None`, `color_scheme: Literal["light","dark","no-preference"]|None`, `user_agent: str|None`, `locale: str|None`, `record_video_dir: str|Path|None`, `record_video_size: tuple[int,int]|None`.
- `response.py:6-25` → add `video_path: Path|None = None` (after `screenshot` `:18`).
- `render_session.py` factory `:111-126` + `RenderSession.__init__ :37-49` — widen with the same emulation/video kwargs (#154 wants it on the session).
- CLI `cli.py`: `--screenshot`/`--screenshot-out` `:109-119`; `RenderOptions(...)` build `:160-165`; add `--device/--viewport WxH/--color-scheme/--user-agent/--locale/--video-out`.
- Tests: `tests/test_patchright_backend.py::_make_pw_chain :18-60` (extend to expose `pw.devices` dict + `context`/`browser`); `tests/test_render_session.py::_make_session_chain :16-41` (already returns context/browser/pw).

### Design (Wave 2)

- `_context_kwargs(pw, opts) -> dict` helper (in the backend, exported like `attach_capture`): resolve `pw.devices[opts.device]` **stripping `default_browser_type`** (new_context rejects it), overlay explicit `viewport`/`user_agent`/etc.; add `record_video_dir`/`record_video_size` (`{"width","height"}`) when set. Resolve **once** in `attempt()`, pass into `_attempt_once`; reuse from `render_session.__enter__`. Extracting it also relieves complexipy on `_attempt_once` (threshold ≤15).
- **Video finalize on `context.close()`**: grab `video=page.video` before close; `_attempt_once` `finally: context.close()` (~`:118-119`) then read `Path(video.path())` onto `Response.video_path`; on a failed/retried attempt (`last.response is None`) `video.delete()` (after close). Same for `render_session._teardown` (read path outside the suppress block).
- **Gotchas:** device dict carries `default_browser_type` (strip); `is_mobile` contexts **clip** not scroll (doc it); Patchright records VP8 `.webm` only.
- `make gif`/`examples/navigate_screencast.py` can switch to core video. Full red-first TDD + docs (api-reference RenderOptions/Response, README, USING, CONTRIBUTING `make` row) + `### Added` fragment.

---

## Cleanup / deletions (after PRs)

- Consolidate emulation dupes **#148/#154/#155** and video dupes **#122/#125** (one canonical each or a "browser-context options" tracker); cross-link.
- **Dedup the SSRF guard** — `contrib/easter_hunt/orchestrator.py:22` still carries a *third* copy of `_check_ssrf`; point it at `utils/_ssrf.check_ssrf` (sitemap + discovery already use the shared one).
- Comment **#127** (scripted `.page` recipe, not core). **Close #60** (UI — off-thesis; shrinks apparent surface). **#89** cheap probe spike → close (downstream).
- Open **pydantic tracking issue** (open-question framing; `scrape-stock-kpi` uses pydantic-settings, polyfetch strips it — `utils/http_ua.py:19`); link from architecture.md.

## Enhancements (fold into the waves)

- **Cut `v0.7.0` around PR A.** The rename is breaking (`Response.backend` value changes) → SemVer-natural release; 0.7.0 also *ships* the already-merged discovery (#135) + screencast under a clean version. Run the **Bump version** workflow after PR A merges; add a **migration note** (`playwright`→`patchright`; deprecated alias) to the release.
- **Scripting cookbook** (`docs/scripting.md` or `examples/`). The two-layer USP asserts "you script the browser on the substrate" — make it real with worked recipes (a11y `aria_snapshot`, a multi-step walk, post-hoc `set_viewport_size`). PR B links it. Low cost, high credibility.
- **Wave-0 DX first** (#145 doctor, #146 venv-borrow docs) — highest value/effort; stops sibling repos silently breaking on wiped Chromium caches.

## Strategic — polyfetch's *estate contract*

**Symptom:** the qte77 estate keeps re-filing the *same* substrate needs from different consumers — emulation (#148 fo-scraper, #154 sfclarity, #155 azure-doc-workflows), video (#122/#125 agenthud/ldnmxx-hack), a shared ui-check helper (#144 fo-scraper/ajoa-kit/sfclarity), doctor (#145), venv-borrow docs (#146), pydantic-settings divergence (`http_ua.py:19`). Each consumer hits the substrate's edge, **drops to raw patchright**, then files an issue → duplicate issues, per-repo script drift, and exactly the raw-patchright workarounds the two-layer positioning is meant to end (#155 explicitly wants polyfetch as "the single browser abstraction").

**Root cause:** polyfetch is the estate's shared fetch/browser substrate, but there's **no explicit contract** for what it owns vs. what each consumer owns — so limits are discovered ad hoc, N times.

**Fix — draw and document the line once (polyfetch owns the *substrate*, not the *framework*):**
1. **polyfetch owns:** the fetch engine; the scripting substrate (installed browser + instrumented `Page` + env-borrow); the `new_context()` knobs (emulation/video — Wave 2 closes the biggest recurring gap); DX tooling (`doctor` #145, documented venv-borrow #146).
2. **Consumers own:** app-specific e2e — the walks, assertions, theme toggling, per-app selectors. Not polyfetch's job.
3. **The one shared helper (#144):** extract only a *minimal* core (render + screenshot + console/404 assert + Make-driveable) once the API settles (AHA) — don't absorb every consumer's wishlist.
4. **Consistency decisions** (pydantic/typing/dataclasses): decide once (the tracking issue) so repos align or diverge *intentionally*.
5. **A short "consuming polyfetch across the estate" doc:** point consumers at env-borrow + the substrate contract + "own your e2e," so they stop re-inventing.

**Payoff:** fewer duplicate issues, less script drift, the single browser abstraction consumers want. **Tension to hold:** this pulls toward an estate *framework*, which fights the minimal-primitive positioning — resolve it by owning the *substrate* (engine + context knobs + DX), never app-specific e2e. Wave 2 + the two-layer docs are steps 1–2; steps 3–5 are the follow-through.

### Where the line is (decidable test) — record in `architecture.md`

**polyfetch owns X iff BOTH:** (a) **generic** — true for *any* target site, not tied to one app's DOM/flow/selectors; **and** (b) **construction-time or shared plumbing** — set at browser/`new_context()` time, or boilerplate every consumer re-implements identically (install/teardown/capture/SSRF). Else **consumer owns** it (app-specific, or a few lines on the `.page` hatch). Applied: emulation/video (#148/#154/#155/#125/#122) = own; a11y `aria_snapshot` (#127) = recipe; ui-check (#144) = minimal core only when stable; doctor/venv-borrow (#145/#146) = own.

### How to move the line (so it stops drifting)

1. **Trigger:** a consumer dropping to *raw patchright* is the signal the line may be wrong.
2. **Promotion rule** (mirrors `.claude/rules/compound-learning`): 1st drop → just script it; 2nd → file/note; **3rd or ≥2 repos need the *identical* thing → promote to core** — *iff* it passes the test above **and** the contract is stable (AHA — don't absorb a moving wishlist).
3. **Record via PR:** into `RenderOptions`/core + update the `architecture.md` boundary statement + changelog entry. The "browser-context options" tracker is the running candidate log.

## Verify → CI-gated PR

- `make validate` green each PR (pyright-strict, complexipy ≤15, cov ≥90, `filterwarnings=["error"]`). PR A live: `--tier patchright`→`backend:"patchright"`; `--tier playwright`→works+warns. PR B: `markdownlint-cli2`+`lychee`; `git grep -niE "hostile|the moat"`→none. Wave 2 e2e: `--device "iPhone 13"`, `--color-scheme dark`, real `.webm`.
- `env -u GH_TOKEN -u GITHUB_TOKEN gh …`; squash on green CI; **check CodeQL** (no `"<url>" in x` — even in test asserts → use `==`). **GitHub Actions webhook delivery was flaky** (dropped PR/push events) — re-trigger (close/reopen or empty push) or wait; a merge conflict may also block (rebase/merge main in).
