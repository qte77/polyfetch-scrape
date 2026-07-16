# Scripting cookbook

Worked recipes for the **scripting substrate** — the second of polyfetch's [two
layers](../README.md#two-layers-engine--scripting-substrate). `render_session(url)`
owns the browser install, launch/teardown, console/network capture, and the SSRF
guard; you own the app-specific steps once you have a live `Page` on `s.page`. Every
snippet below uses only the public `RenderSession` surface: `click` / `click_text` /
`fill` / `submit` / `wait_for_selector` / `wait_for_function` / `wait_ms` / `shot`,
plus `.page`, `s.console_errors`, `s.network_failures`, `s.screenshots`, and
`s.video_path`.

## DevTools capture

Wire any `page.on(...)` listener to react to DevTools events as the page runs — the
same signals the Chrome DevTools console/network panels show:

```python
from polyfetch_scrape import render_session

with render_session(url) as s:
    s.page.on("console", lambda m: print(m.type, m.text))          # console.log/warn/error
    s.page.on("pageerror", lambda e: print("uncaught JS:", e))     # uncaught JS exceptions
    s.page.on("requestfailed", lambda r: print(r.url, r.failure))  # failed network requests
    s.click_text("Load more")

    print(s.console_errors)     # always-on: console + uncaught-JS errors, whole session
    print(s.network_failures)   # always-on: failed / >=400 requests, whole session
```

You don't have to wire listeners at all — `s.console_errors` and `s.network_failures`
fill for the whole session (initial page load included) with no setup.

> **Caveat:** a headless capture reflects only *this* runner's network. A cross-origin
> failure a real user hits (CORS, a browser extension, a proxy) can succeed here and
> read clean — treat an empty capture as "no error on this network", not "no error".

## Accessibility snapshot

```python
with render_session(url) as s:
    snap = s.page.locator("body").aria_snapshot()
```

`aria_snapshot()` is the current Patchright API for reading the accessibility tree;
`page.accessibility.snapshot()` was removed upstream, so don't reach for it.

## Multi-step walk

A realistic act → assert → act flow — drive the page, wait for the result to settle,
then act again:

```python
with render_session(url) as s:
    s.click_text("Live")
    s.wait_for_selector("input:not([disabled])")
    s.fill("input", "hello")
    s.submit()
    s.wait_for_selector(".message:last-child")
    s.shot("after")
```

On an exception inside the `with` block, `render_session` captures an `"exception"`
screenshot into `s.screenshots` before teardown — useful for post-mortem debugging a
failed walk without adding your own try/except.

## Live emulation on `.page`

`s.page` exposes Patchright's live emulation calls for changes mid-session:

```python
with render_session(url) as s:
    s.page.set_viewport_size({"width": 1280, "height": 720})
    s.page.emulate_media(color_scheme="dark")
```

These are the *post-hoc* hatches. `device` / `locale` / `user_agent` / video are
context-time only — set once as `render_session(...)` (or `RenderOptions`) arguments,
because they apply at browser `new_context()` time and can't be changed after the page
exists. `viewport` and `color_scheme` sit on the seam: pass them once at
`render_session(...)` time, or change them live on `.page` as above — see
[Two layers](../README.md#two-layers-engine--scripting-substrate) for the full split.

## What NOT to do

`page.evaluate` runs in an **isolated execution world** under Patchright (a stealth
Playwright fork), not the page's main world. The DOM is shared, but a JS global the
page's own scripts define (`window.Foo`) reads back as `undefined` from `evaluate`
even though it exists and works in the page:

```python
with render_session(url) as s:
    s.page.evaluate("() => typeof window.Foo")   # "undefined" — even if Foo is defined and used
```

Don't assert page-script globals via `evaluate`. Use `s.shot(name)` (screenshots) as
ground truth for "did it render", `page.on(...)` for "did it load", and reserve
`evaluate` for DOM you set or read structurally — element presence, attributes,
`textContent`.
