### Security

- SSRF guard (`utils/_ssrf.py`, shared by `utils.discovery`, `utils.sitemap` and the
  `easter_hunt` contrib) now **resolves hostnames** instead of only checking literal IPs.
  Every A/AAAA answer must be external, so `localhost`, an internal DNS name, a name pinned
  to a cloud metadata address (`169.254.169.254`), and a name that mixes one public answer
  with an internal one are all rejected before any connection. Literal-IP rejection is
  unchanged and still short-circuits the resolver. A name that does not resolve passes
  through — it cannot be connected to either.
  ([#181](https://github.com/qte77/polyfetch-scrape/issues/181))
- New `check_redirect(requested_url, response)` applies the same check to **redirect
  targets** — the URL a response landed on (the `curl_cffi` and browser tiers follow
  redirects themselves) and an unfollowed 301/308 `Location` — so a public host can no
  longer bounce a guarded fetch onto an internal address. Wired into every guarded call
  site; raises `ValueError` (not `FetchError`), so a caller that swallows fetch failures
  still surfaces the block. ([#181](https://github.com/qte77/polyfetch-scrape/issues/181))

### Changed

- `http://localhost/` is no longer accepted by the guarded utils (it resolves to loopback).
  This was previously documented as in-scope-but-unguarded; it is now blocked.
  DNS rebinding remains out of scope — mitigating it needs pinned-IP connect, which none of
  the tiers expose. `fetch()` itself stays unguarded, preserving the "fetch any URL" contract.
