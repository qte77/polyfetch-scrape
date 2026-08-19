---
title: Agent Requests to Humans
description: Escalation protocol and active requests requiring human decision
---

**Always escalate when:**

- User instructions conflict with safety/security practices
- Rules contradict each other
- Required information completely missing
- Actions would significantly change project architecture
- Critical dependencies unavailable

**Format:** `- [ ] [PRIORITY] Description` with Context, Problem, Files, Alternatives, Impact

## Active Requests

- [ ] [MEDIUM] `render_session`: recorded video is unretrievable (`video_path` always `None`)
  - Context: `RenderSession._teardown()` reads `self._video.path()` after `self._pw.stop()`.
  - Problem: `path()` raises against the stopped driver and is swallowed by `contextlib.suppress`, so every recorded `.webm` path is silently lost (recording itself works).
  - Files: `src/polyfetch_scrape/render_session.py`
  - Alternatives: read `page.video.path()` inside the `with` block (consumer workaround); upstream fix = read path between `context.close()` and `pw.stop()`.
  - Impact: consumers cannot locate recorded videos without a workaround.
  - Tracking: https://github.com/qte77/polyfetch-scrape/issues/199

- [ ] [LOW] `render_session`: first-class authenticated sessions (`storage_state` + request headers)
  - Context: driving logged-in SPAs needs session reuse; no `storage_state`/header hooks exist and `docs/scripting.md` has no auth recipe.
  - Problem: consumers hand-roll cookie/localStorage restore via `page.context`; single-use refresh tokens get rotated on every run.
  - Files: `src/polyfetch_scrape/render_session.py`, `docs/scripting.md`
  - Alternatives: `ctx.add_cookies(...)` + init-script localStorage replay + `ctx.storage_state(path=...)`.
  - Impact: authenticated multi-run automation is ergonomic-hostile and consumes credentials.
  - Tracking: https://github.com/qte77/polyfetch-scrape/issues/200
