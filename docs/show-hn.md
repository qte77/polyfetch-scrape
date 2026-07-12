<!-- markdownlint-disable MD013 MD033 -->
# Show HN — launch draft

> **Status: draft, not posted.** This is in-repo copy to iterate on. Actually
> submitting to Hacker News (or anywhere) is a separate, deliberate step — see
> [Before you post](#before-you-post). Positioning here follows an adversarial
> red-team of the launch angle: lead with the concrete problem, concede the
> ceiling up front, and claim no moat.

## Title

> **Show HN: polyfetch — a fetch() that falls back from plain HTTP to TLS impersonation to a real browser, only when blocked**

Alternative (if deliberately targeting the agent-tooling crowd):

> Show HN: polyfetch — I built a fetch() for when my scraper's User-Agent swap didn't fix the 403

## Post body

My script's HTTP client got a `403`. Swapping the `User-Agent` didn't fix it —
the block keyed on the TLS handshake, not the header. So the fix isn't a better
UA string, it's a client that *speaks* like a browser: same TLS/JA3 handshake,
same header shape, and — only when that still isn't enough — a real headless
browser. `polyfetch` is one `fetch()` that walks that ladder for you and returns
a typed result no matter which rung cleared.

```python
from polyfetch_scrape import fetch

r = fetch("https://nowsecure.nl/")
print(r.status, r.backend)   # 200 curl_cffi  — tier 1 (httpx) got 403; it escalated
```

One call, three tiers, tried cheapest-first and escalated **only on an actual
block**:

1. `httpx` — plain HTTP with browser-shaped headers.
2. `curl_cffi` — replays a real Chrome TLS/JA3 handshake (what a header edit can't do).
3. Patchright — headless Chromium with anti-detection patches, for JS-rendered pages.

`Response.backend` tells you which tier succeeded. You can pin one tier or bound
the range (`tier` / `min_tier` / `max_tier`) when you don't want a browser to
ever launch.

### Why a UA swap isn't enough (real, point-in-time data)

From the repo's own probes — **re-run before you rely on these; anti-bot rules
decay** ([full table + citations](scraping-landscape.md)):

| Client requesting `www.hamiltoncompany.com` (probed 2026-07-06) | Status |
|---|---|
| `curl` with its default UA | `403` |
| `curl` **with a Firefox UA + browser `Accept` + Google `Referer`** | `403` |
| polyfetch `httpx` tier (browser headers, OpenSSL TLS) | **`200`** |
| polyfetch `curl_cffi` tier (Chrome TLS/JA3 impersonation) | **`200`** |

Both `403` rows already carry a *browser* User-Agent. The discriminating factor
is the broader client profile (header set and/or TLS signature), not the UA
string — which is the whole reason the TLS-impersonation tier exists.

### What else it does (all shipped)

- **Typed errors instead of parsing status codes yourself.** `401/407 →
  AuthRequired`, `404/410 → GoneError`, `451 → LegalBlock`; `429/5xx` retry
  honouring `Retry-After`. Same typed error whichever tier served the request.
- **Browser-tier depth** (Patchright tier): single + named **screenshots**,
  scripted actions (click / fill / wait), an interactive multi-step
  `render_session`, and opt-in console/network-failure capture.
- **Conditional GET** (`etag` / `last_modified` → `304`), a per-host `Throttle`,
  and POST bodies (`json` / `content`).
- **Library, CLI, or env-borrow.** `import fetch`, run `polyfetch`, or sideload
  from another repo/agent **without installing** it (`uv run --directory`).

### What it deliberately does **not** do

- **No proxy or residential-IP rotation** → not built for large-scale crawling;
  the moment a target blocks by IP reputation, this alone won't save you.
- **No content extraction** — no LLM/markdown/readability layer. You get bytes +
  a typed `Response`; parsing is yours.
- **No hosted service, no CAPTCHA solving, no paywall bypass.** It reaches pages
  the same way a browser already can — nothing more.

### The honest ceiling (stated up front, not buried)

The headless-Chromium tier **does not clear enterprise-grade bot management**.
In-repo, `g2.com` (Cloudflare Enterprise) returns `403` through *all three*
tiers. Patchright *can* pass Cloudflare — but only in its recommended config
(**headed**, real Chrome, `launch_persistent_context`), which is incompatible
with most CI/server environments. Headless + Chromium leaves residual
fingerprints (window dims, GPU strings, headless-shell binary) that enterprise
Cloudflare still reads. That CI-incompatibility is the actually load-bearing
constraint — [details + citations](scraping-landscape.md). Two smaller edges to
know: full-page screenshots are unsupported (element/viewport only), and
console/network capture reflects only *this* process's network (a failure a real
user hits via CORS/extension/proxy can read clean here).

### Prior art

No new evasion technique here. `curl_cffi` and Patchright do the hard parts;
`cloudscraper` and `undetected-chromedriver` have long solved adjacent problems.
What polyfetch adds is *composition*: one call, cheapest-first escalation, and a
typed `Response`/error surface — so a caller stops hand-rolling a
try/except-and-escalate loop per site. If that convenience isn't worth a
dependency to you, hand-rolling it is genuinely fine.

### Who it's for

A single script or small agent that occasionally hits basic-to-intermediate bot
detection and wants **one call that tries the cheap path first and escalates to
TLS impersonation or a headless browser only when actually blocked** — not
large-scale crawling (no proxy rotation) and not content extraction (no
LLM/markdown layer).

Repo: `https://github.com/qte77/polyfetch-scrape` · [README](../README.md) ·
[API reference](api-reference.md) · [Using without installing](../USING.md).
Apache-2.0, Python ≥ 3.11.

---

## Before you post

Internal checklist — do these before submitting, not in the post:

- **Re-run the probes.** The `hamiltoncompany.com` / `nowsecure.nl` / `g2.com`
  numbers are point-in-time (`make probe URL=...`). If any flipped, update the
  table or drop the example — shipping stale block data is the fastest way to
  get corrected in the comments. (See AGENT_LEARNINGS: empirical data decays.)
- **Link only user-facing docs** from the post: README, `api-reference.md`,
  `USING.md`. Do **not** link `AGENTS.md`, `AGENT_LEARNINGS.md`, or the release
  pipeline — contributor process docs read as "more governance than product"
  around a ~1.5k-line library and invite a pile-on.
- **Lead with the g2.com ceiling, don't let it be discovered.** Framed as
  "here's what it doesn't clear," it reads as honesty; found by a commenter, it
  reads as overclaiming.
- **Cut moat words.** No "wedge", "reactive tiering", or "typed taxonomy" as
  headline claims — plain verbs only. This is a small honest utility, not a
  platform.

### The risk copy can't fix

The biggest credibility risk isn't the Cloudflare-Enterprise ceiling (that's
disclosable). It's the **mismatch between "small honest utility" and the repo's
visible footprint** — `AGENTS.md`, skills/rules dirs, a two-step bump-and-tag
release pipeline with changelog fragments — all wrapped around ~1,500 lines.
Show HN readers click through to GitHub. Copy can't patch that; only the repo's
actual surface can. Decide whether to slim the visible process footprint before
launch, or to own it explicitly ("yes, this is over-engineered for its size, on
purpose — here's why").
