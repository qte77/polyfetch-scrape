# 005 — #118 opt-in console / network-failure capture on `Response`

> Status: **planned, not started.** Handoff: `docs/handoffs/005-render-console-network-capture.md`.
> Repo `main`; Python CI is live (`Test / ci` gates every PR). One CI-gated PR.
> **Decisions locked (maintainer):** capture **both** network signals (`requestfailed` **and**
> HTTP `status >= 400`); **full** doc set; **library-only** (no CLI flag — `--json` surfacing is #105).
> **Standing bar:** strict TDD red-first · lint + security · non-trivial tests only (test modules with
> real logic, not trivial glue).

## Context

The browser tier gives no first-class way to read a page's **console errors** / **failed requests** — every
consumer re-hand-wires `page.on(...)` in raw Patchright, and (per AGENT_LEARNINGS #3) easily mis-reads the
**runner-network caveat**. #118 adds opt-in capture surfaced on the typed `Response`, off by default. Small,
additive, CI-testable; the capture it adds is reused by the future #117 session.

## Source map — read these, don't re-explore

**Repo facts:** src layout `src/polyfetch_scrape/`; make-driven (never bare `pip`/`pytest`/`ruff`/`pyright`);
pyright **strict**, `include=["src"]` (**tests are NOT type-checked**); complexipy threshold 15; coverage
≥ 90; e2e skipped by default. `gh` needs `env -u GH_TOKEN -u GITHUB_TOKEN`. `make ci` = check-only
`ruff format --check` + `ruff check` + `pyright src` + `complexipy -q .` + `pytest --cov`.

| File / anchor | What's there / what to do |
|---|---|
| `src/polyfetch_scrape/render_options.py` | `RenderOptions` dataclass **l.27-46** (`frozen=True, slots=True`); fields end at `actions: tuple[RenderAction, ...] = ()` **l.46**. **Add** two `bool = False` fields after `actions` (+ two docstring bullets). |
| `src/polyfetch_scrape/response.py` | `Response` dataclass **l.6-18** (`frozen=True, slots=True`); import line **l.2** `from dataclasses import dataclass`; last fields `permanent_redirect_to=None` l.16, `screenshot=None` l.18. **Change** l.2 → `from dataclasses import dataclass, field`; **add** two `field(default_factory=list)` fields after `screenshot`. All constructions are keyword (backends+tests) → end-append is safe; httpx/curl get empty defaults untouched. |
| `src/polyfetch_scrape/_backends/playwright_backend.py` | `_attempt_once` **l.66-113**. Page created **l.77** `page = context.new_page()`; inner `try:` l.78; success `Response(...)` built **l.98-111** (after `_apply_waits` l.94). `RenderOptions` already imported (l.15); `from typing import Any` present (l.4). **Add** `_attach_capture` + `_record_console` + `_record_bad_response` helpers; call `_attach_capture` right after l.77 (before `goto`); thread the two lists into the l.98-111 `Response(...)`. |
| `src/polyfetch_scrape/client.py` | **NO change** — `render` (RenderOptions) is already threaded to the playwright tier. |
| `tests/test_playwright_backend.py` | `_make_pw_chain` helper **l.18-60** (builds MagicMock `page/context/browser`, monkeypatches `sync_playwright`; `page = MagicMock(spec=pw_sync.Page)` so `page.on` is an auto-mock recording `call_args_list`). `_no_sleep` autouse fixture l.13-15. `pw_sync` imported l.5. Existing tests pass `render=RenderOptions(...)`. **Add** the 3 capture tests below — no change to `_make_pw_chain` needed (retrieve handlers from `page.on.call_args_list`, fire synthetic events; the `Response` holds the SAME list objects by reference, so post-return appends are visible). |
| `docs/api-reference.md` | `## Render controls` block (the `RenderOptions(...)` python fence) + `## Response and RetryPolicy` block (the `Response(...)` fence). Add the flags + fields + caveat. |
| `docs/architecture.md` · `docs/roadmap.md` · `docs/userstory.md` · `CHANGELOG.md` | Full-doc-set touches (see Docs section). |

## Design (exact code)

**`render_options.py`** — append to `RenderOptions` (after `actions`), and add two docstring bullets:

```python
    actions: tuple[RenderAction, ...] = ()
    capture_console: bool = False
    capture_network_failures: bool = False
```

**`response.py`** — `from dataclasses import dataclass, field`, then append to `Response`:

```python
    screenshot: bytes | None = None
    # Browser-tier diagnostics — opt-in via RenderOptions.capture_*; empty on the httpx/curl tiers.
    # NOTE: reflects only THIS process's network — a failure a real user hits (CORS / extension /
    # proxy) can read clean here. Force a known failure to trust it (AGENT_LEARNINGS #3).
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[dict[str, object]] = field(default_factory=list)
```

**`_backends/playwright_backend.py`** — new module helpers + one call + two kwargs:

```python
def _record_console(msg: Any, sink: list[str]) -> None:
    if msg.type == "error":
        sink.append(str(msg.text))


def _record_bad_response(resp: Any, sink: list[dict[str, object]]) -> None:
    if int(resp.status) >= 400:
        sink.append({"url": str(resp.url), "status": int(resp.status)})


def _attach_capture(page: Any, opts: RenderOptions) -> tuple[list[str], list[dict[str, object]]]:
    """Register opt-in console/network listeners; return the (still-filling) capture lists.

    A headless capture reflects only THIS process's network — a cross-origin failure a real user
    hits (CORS / extension / proxy) can succeed here and read clean. Force a known failure to
    trust it (AGENT_LEARNINGS: "Headless console/network capture only reflects the runner's own network").
    """
    console_errors: list[str] = []
    network_failures: list[dict[str, object]] = []
    if opts.capture_console:
        page.on("console", lambda m: _record_console(m, console_errors))
        page.on("pageerror", lambda e: console_errors.append(str(e)))
    if opts.capture_network_failures:
        page.on(
            "requestfailed",
            lambda r: network_failures.append({"url": str(r.url), "error": str(r.failure)}),
        )
        page.on("response", lambda r: _record_bad_response(r, network_failures))
    return console_errors, network_failures
```

In `_attempt_once`: after `page = context.new_page()` (l.77) add
`console_errors, network_failures = _attach_capture(page, opts)`; in the success `Response(...)` (l.98-111)
add `console_errors=console_errors, network_failures=network_failures,` after `screenshot=...`.

**Why it holds complexity < 15:** the filters live in `_record_*`; `_attempt_once` gains one call + two
kwargs (no new branches). **Typing:** annotate the sinks `list[dict[str, object]]` so the appended dict
literals get expected-type context (avoids pyright dict-invariance under strict).

## Strict TDD (red first) — `tests/test_playwright_backend.py`

Add small fakes (`_fake_console(type,text)`, `_fake_request(url,failure)`, `_fake_response(status,url)` →
`MagicMock`s with those attrs) and:

1. **`test_..._captures_console_and_network`** — `attempt(..., render=RenderOptions(capture_console=True,
   capture_network_failures=True))`; build `handlers = {c.args[0]: c.args[1] for c in page.on.call_args_list}`;
   fire `handlers["console"](_fake_console("error","boom"))`, `handlers["pageerror"]("Uncaught X")`,
   `handlers["requestfailed"](_fake_request("https://x/api","net::ERR"))`,
   `handlers["response"](_fake_response(500,"https://x/500"))`; assert `"boom"` and `"Uncaught X"` in
   `resp.console_errors`, and `{"url":"https://x/api","error":"net::ERR"}` + `{"url":"https://x/500","status":500}`
   in `resp.network_failures`. (Works because `resp.console_errors is` the same list the handlers append to.)
2. **`test_..._console_filter_ignores_non_error`** — fire `handlers["console"](_fake_console("log","x"))`
   → `resp.console_errors == []`.
3. **`test_..._no_capture_by_default`** — no flags → `resp.console_errors == [] and resp.network_failures == []`
   **and** `{"console","pageerror","requestfailed","response"}` ∩ `{c.args[0] for c in page.on.call_args_list}`
   is empty (opt-in gating → zero overhead).
- Regression: existing playwright/httpx/curl/client tests stay green (defaults empty elsewhere).

## Docs (full set, lockstep)

- `docs/api-reference.md`: add `capture_console` / `capture_network_failures` to the `RenderOptions` fence;
  add `console_errors` / `network_failures` to the `Response` fence **with the runner-network caveat**.
- `CHANGELOG.md ### Added` — the capture feature. `Closes #118`.
- `docs/architecture.md`: the `render_options.py` responsibility row → mention console/network capture.
- `docs/roadmap.md`: add to the shipped "Browser-tier depth (the moat)" facet list.
- `docs/userstory.md`: one line on the existing "Caller scraping a JS-rendered page" story (assert 0 console errors).
- No `README.md`/`USING.md` change (no CLI/JSON surface this unit).

## Verify → CI-gated PR

1. `make validate` **and** `make ci` green (ruff strict, pyright strict 0 errors, complexipy < 15, cov ≥ 90).
2. **Security**: run the `/security-review` pass on the diff — listeners collecting strings/dicts, no new
   sink; confirm the runner-network caveat is documented (expected clean).
3. `markdownlint-cli2` + `lychee --config lychee.toml` clean on touched docs.
4. Branch `feat/render-capture`; topical commits (render_options+response+backend core / docs);
   PR `Closes #118`; watch `gh pr checks --watch`; squash-merge **only** when all checks pass (never
   `--admin`); `--delete-branch` + `git fetch --prune`; keep `main` the only local branch.
