# Consuming polyfetch across the estate

How the qte77 estate consumes **one** shared `polyfetch-scrape` — the horizontal
HTTP-scraping substrate — from many downstream repos, and the rule for when a
consumer's need becomes core. This is the map; the contracts it points at are
authoritative.

- **Call contract** (invocation, `--json` schema, errors, stable surface):
  [`USING.md`](../USING.md).
- **Engine internals** (fallback chain, components, invariants):
  [`docs/architecture.md`](architecture.md).
- **Human overview**: [`README.md`](../README.md).

## The estate model

polyfetch is **horizontal**: it fetches bytes over a reactive `httpx → curl_cffi →
Patchright` fallback chain and returns a typed `Response`. It knows nothing about any
one consumer's domain. Downstream repos (feed actions, application kits, orchestrators)
are the **vertical** layer — they consume `fetch()` / `render_session()` and add their
own site-specific walks, selectors, extraction, and assertions.

One engine, many consumers. Consumers **borrow** polyfetch's environment rather than
installing it (below), so its heavy deps (patchright, curl_cffi, httpx) never enter a
consumer's lockfile.

## The ownership line (who owns what)

The decidable test lives in [`architecture.md`](architecture.md#two-layers-engine-and-scripts)
and is the single source of truth. In short:

- **polyfetch owns X** iff X is **(a) generic** — true for any target site, not tied to
  one app's DOM/flow — **and (b) construction-time or shared plumbing** — set at
  browser/`new_context()` time, or boilerplate every consumer re-implements identically
  (install, teardown, capture, SSRF guard).
- **The consumer owns X** otherwise — app-specific walks, selectors, and assertions, or a
  few lines on the `render_session().page` escape hatch.

Applied: device/locale/viewport/user-agent/video emulation → engine (`new_context()`-time);
`aria_snapshot`, multi-step interactive walks, per-app screenshots → scripted `.page`
recipes in the consumer.

## How a consumer borrows it

Env-borrow via `uv run --directory` — the full contract (commands, `--json` schema, exit
codes, stable surface) is in [`USING.md`](../USING.md). The one-line shape:

```bash
uv run --directory <polyfetch> polyfetch fetch <url> --json
```

`<polyfetch>` is the consumer's checkout of this repo (git submodule or sibling clone). It
runs in polyfetch's **own** `.venv`; the consumer's environment is never touched. Consumers
pick one of two modes — out-of-process (call the CLI, parse `--json`; recommended for agents)
or in-clone script (`uv run --directory <polyfetch> python /abs/script.py` for the full
Python API). See [`USING.md`](../USING.md) for both.

## Promotion rule — when a consumer need becomes core

A capability a consumer builds on `.page` gets **promoted into the engine** only when it
passes the ownership line **and** the pattern is stable and shared:

1. It is **generic + construction-time/shared plumbing** (the ownership test above) — not
   app-specific.
2. **At least two consumers need the identical thing**, and its API has settled (avoid a
   hasty abstraction — duplication is cheaper than the wrong shared surface).

Until both hold, the capability stays in the consumer as a `.page` recipe (see the
[scripting cookbook](scripting.md)). This is why some ergonomic helpers (e.g. a shared
render + screenshot + console/404-assert ui-check) remain deferred rather than in core: the
second consumer and the stable API aren't there yet.
