# 007 — Positioning + `patchright` rename + emulation/video → core RenderOptions

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
| #147 robots | M | M | backlog (#153) · #59 captcha handoff | backlog (niche) |
| #89 USPTO | L | spike | spike→close (downstream) · #60 UI | **close** (off-thesis) |

Order: #105/006 → #139 merges (patchright 1.61.2) → Wave-1 rename → Wave-2 emulation (on renamed code + newer patchright).

---

## Wave 1 · PR A — rename `playwright` tier → `patchright`  (`refactor/rename-patchright-tier`)

Breaking-ish (pre-1.0). Keep `"playwright"` as a **deprecated input alias** (map→`patchright` + `DeprecationWarning`) — live sibling consumers pass `--tier playwright`.

### Source map (label = the string `"playwright"`)
- `src/polyfetch_scrape/response.py:13` — `backend: Literal["httpx","curl_cffi","playwright"]` → `…,"patchright"]`. **The one unavoidable break:** `Response.backend` now returns `"patchright"`.
- `src/polyfetch_scrape/client.py:29` `Tier = Literal[...]`; `:42` `_TIER_ORDER`; `:114` `hi: Tier = … "playwright"`. Dispatch `_run_chain`→`_dispatch` (~:120-168) calls `playwright_backend.attempt(...)` at `:168`.
- `src/polyfetch_scrape/cli.py:20-34` `_TierChoice(StrEnum)` (`:29` `playwright="playwright"`) + `_as_tier` (`:31-33`, `cast` to `Tier`).
- `src/polyfetch_scrape/_backends/playwright_backend.py:108` — `backend="playwright"` in the Response build.
- Module refs to rename: file `_backends/playwright_backend.py` → `patchright_backend.py`; importers `client.py`, `render_session.py:23` (`from …_backends.playwright_backend import attach_capture, capture_screenshot`), tests below.
- Tests w/ the label (flip to `"patchright"`): `tests/test_cli.py:90,147,152,220,233`; `tests/test_client.py:292,323,378,384,386,434,439,476,496,501,518,540,542,571`; `tests/test_e2e.py:95,135`; `tests/test_playwright_backend.py:78` (rename file → `test_patchright_backend.py`).

### Design
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

### Design
- `_context_kwargs(pw, opts) -> dict` helper (in the backend, exported like `attach_capture`): resolve `pw.devices[opts.device]` **stripping `default_browser_type`** (new_context rejects it), overlay explicit `viewport`/`user_agent`/etc.; add `record_video_dir`/`record_video_size` (`{"width","height"}`) when set. Resolve **once** in `attempt()`, pass into `_attempt_once`; reuse from `render_session.__enter__`. Extracting it also relieves complexipy on `_attempt_once` (threshold ≤15).
- **Video finalize on `context.close()`**: grab `video=page.video` before close; `_attempt_once` `finally: context.close()` (~`:118-119`) then read `Path(video.path())` onto `Response.video_path`; on a failed/retried attempt (`last.response is None`) `video.delete()` (after close). Same for `render_session._teardown` (read path outside the suppress block).
- **Gotchas:** device dict carries `default_browser_type` (strip); `is_mobile` contexts **clip** not scroll (doc it); Patchright records VP8 `.webm` only.
- `make gif`/`examples/navigate_screencast.py` can switch to core video. Full red-first TDD + docs (api-reference RenderOptions/Response, README, USING, CONTRIBUTING `make` row) + `### Added` fragment.

---

## Cleanup / issues (after PRs)
- Consolidate emulation dupes **#148/#154/#155** and video dupes **#122/#125** (one canonical each or a "browser-context options" tracker); cross-link.
- Open **pydantic tracking issue** ("Evaluate pydantic/pydantic-settings — estate consistency vs minimal library", open-question framing; `scrape-stock-kpi` uses pydantic-settings, polyfetch strips it — see `utils/http_ua.py:19`); link from architecture.md.
- Comment **#127** (scripted `.page` recipe, not core). Recommend close **#60**. **#89** cheap spike→close.

## Verify → CI-gated PR
- `make validate` green each PR (pyright-strict, complexipy ≤15, cov ≥90, `filterwarnings=["error"]`). PR A live: `--tier patchright`→`backend:"patchright"`; `--tier playwright`→works+warns. PR B: `markdownlint-cli2`+`lychee`; `git grep -niE "hostile|the moat"`→none. Wave 2 e2e: `--device "iPhone 13"`, `--color-scheme dark`, real `.webm`.
- `env -u GH_TOKEN -u GITHUB_TOKEN gh …`; squash on green CI; **check CodeQL** (no `"<url>" in x` — even in test asserts → use `==`). **GitHub Actions webhook delivery was flaky** (dropped PR/push events) — re-trigger (close/reopen or empty push) or wait; a merge conflict may also block (rebase/merge main in).
