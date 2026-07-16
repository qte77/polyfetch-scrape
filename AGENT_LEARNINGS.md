---
title: Agent Learning Documentation
description: Non-obvious patterns that prevent repeated mistakes across sprints
---

## Template

- **Context**: When/where this applies
- **Problem**: What issue this solves
- **Solution**: Implementation approach
- **Example**: Working code
- **References**: Related files

## Learned Patterns

### Parse untrusted XML/RSS with defusedxml, never stdlib ElementTree

- **Context**: Any path parsing third-party XML/RSS/Atom from an untrusted URL — a downstream source/adapter package or future feed wrapper. Core has no XML parsing today, so this is a standing/preventive rule.
- **Problem**: Python's stdlib `xml.etree.ElementTree` is vulnerable to XXE (external-entity expansion) and billion-laughs entity-expansion DoS on untrusted input — flagged by Bandit B314.
- **Solution**: Parse untrusted XML with `defusedxml` (e.g. `defusedxml.ElementTree.fromstring`), or plain-regex extraction for trivial cases; never call `xml.etree.ElementTree` on untrusted payloads. Pairs with the AGENTS.md "Network caution" bullet.
- **References**: AGENTS.md "Core Rules & AI Behavior → Network caution". Issue #42. (The prior in-tree example `sources/arxiv.py` was extracted from core with the arXiv wrapper.)

### Verify single-subagent claims before propagating

- **Context**: Spawning a subagent (Task tool, or any nested agent) to gather facts about external vendors, products, or third-party code that the subagent cannot fetch directly.
- **Problem**: Subagents without web access fabricate plausible-but-wrong specifics from training data. Observed twice in one session: "BIQU Hurakan belt mod" and "White Knight by Annex Engineering" — both confidently asserted, both wrong on first-party verification.
- **Solution**: Treat any single-subagent vendor/product/library attribution as a hypothesis until a first-party source (vendor site, official docs, package registry, gh API) confirms it. Verify *before* threading the claim into a PR, issue body, or documentation. The verification step is cheap; the propagation cost is high once the fabrication is in code review or the changelog.
- **Example**: When a subagent returns "Library X, by Author Y, MIT license, used by Project Z", before quoting any of those, fetch the project's actual README / PyPI page / repo. If any of the four facts is wrong, all four are suspect.
- **References**: This learning has no in-tree code reference — it is a workflow rule. Compound-learning promotion path: stays in `AGENT_LEARNINGS.md` until a second occurrence justifies promoting to `.claude/rules/`.

### Headless console/network capture only reflects the runner's own network

- **Context**: Driving the Patchright/Chromium backend (`_backends/patchright_backend.py`, or raw `patchright.sync_api`) to debug a page's runtime behaviour — capturing console logs, JS errors, and network failures via `page.on(...)`.
- **Problem**: `page.on("console" | "pageerror" | "requestfailed" | "response")` faithfully captures the page's telemetry — but only for traffic on **this process's network**. A cross-origin fetch the page makes (e.g. to `raw.githubusercontent.com`) that is blocked in a *user's* browser (CORS / privacy extension / proxy / per-IP rate-limit) **succeeds here**, so the capture comes back clean — a false "no error" conclusion. Observed while debugging a dashboard that silently fell back to synthetic data in the reporter's Firefox (`CORS request did not succeed`) but loaded real data from this container.
- **Solution**: Read a clean headless console as "no error *on this network*", not "no error". To trust the capture for an environment-specific failure, **force the failure** (e.g. point the fetch at an unreachable host) and confirm the listeners catch it; otherwise reason from the deployed code + the data's reachability, not the headless console alone. Capture all four events: uncaught/parse errors fire `pageerror` (**not** `console`); blocked/!2xx resources fire `requestfailed` / a non-200 `response` (not always `console`).
- **Example**: `page.on("requestfailed", lambda r: ...)` → `net::ERR_NAME_NOT_RESOLVED` when the page fetches `https://nonexistent.invalid/...`; the same page on a reachable network logs nothing for that request.
- **References**: `src/polyfetch_scrape/_backends/patchright_backend.py` (the Patchright/Chromium backend). Workflow rule — stays in `AGENT_LEARNINGS.md`.

### page.evaluate runs in an isolated world — page-script globals read as `undefined`

- **Context**: Driving the Patchright/Chromium backend (`_backends/patchright_backend.py`, or raw `patchright.sync_api`) and reading page state via `page.evaluate(...)` to assert on runtime values — a library global (`window.Chart` from a UMD bundle) or a module-scoped var set by the page's own scripts.
- **Problem**: Patchright (a stealth Playwright fork) runs `page.evaluate` in an **isolated execution world**, not the page's main world. The DOM is shared, but JS globals defined by the page's own scripts (`window.Chart`, any module-scoped var) read back as `undefined` from `evaluate` even though they exist and work in the page. Caused a false "Chart is undefined / the chart didn't render" conclusion when the chart had in fact rendered.
- **Solution**: Don't assert page-script globals via `page.evaluate` under Patchright. Use **screenshots as ground truth** for "did it render / what's shown", and `page.on(...)` for "did it load". Reserve `evaluate` for DOM you set or read structurally (element presence, attributes, `textContent`), not library/module globals.
- **Example**: `page.evaluate("() => typeof window.Chart")` → `"undefined"` while the chart is visibly rendered; `page.locator('#chart-section').screenshot(...)` shows the real chart.
- **References**: `src/polyfetch_scrape/_backends/patchright_backend.py` (the Patchright/Chromium backend). Pairs with the "Headless console/network capture only reflects the runner's own network" learning above. Workflow rule — stays in `AGENT_LEARNINGS.md`.

### Re-verify time-sensitive empirical data before merging — it decays

- **Context**: Merging empirical / observational data that was captured earlier — in an issue body, a prior doc, or a past agent session — into the tree: anti-bot probe tables, "site X returns 403" claims, status-code observations, timing numbers.
- **Problem**: Anti-bot rules, site policies, and network conditions change fast; data accurate when captured is often stale by merge time. Observed: issue #36 proposed a six-site "default-UA vs. browser-UA" block table from an earlier session; on re-probe **5 of the 6 sites had flipped** (now `200` to a bare `curl`), and the one remaining blocker discriminated on the **TLS/client fingerprint, not the UA string** — inverting the issue's thesis. Merging verbatim would have shipped a wrong conclusion.
- **Solution**: Before merging time-sensitive empirical data, **re-run the probe/measurement yourself** via the sanctioned ad-hoc path (`make probe`, or `curl`), use the fresh values, and note any deviation in the PR body. Stamp tables with a "probed YYYY-MM-DD" date and keep the doc's own "point-in-time — re-run before relying" caveat. Extends [Verify single-subagent claims before propagating] from *fabrication* to *decay*.
- **References**: `docs/scraping-landscape.md` "Empirical findings — polyfetch-scrape probes"; issues #36 / #39. Workflow rule — stays in `AGENT_LEARNINGS.md`.
