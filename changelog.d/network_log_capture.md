### Added

- Opt-in **full network log** on the patchright tier. `RenderOptions(capture_network_log=True)`
  → `Response.network_log`, and `render_session(url, capture_network_log=True)` →
  `RenderSession.network_log`, recording **every** completed request as
  `{url, method, status, duration_ms}` (not just the failures `network_failures` keeps).
  `status`/`duration_ms` are `None` for a request that failed outright or that the browser
  reported no timing for. Off by default — zero listeners, zero overhead unless asked — and
  independent of `capture_network_failures`, whose behaviour is unchanged.
  ([#182](https://github.com/qte77/polyfetch-scrape/issues/182))
