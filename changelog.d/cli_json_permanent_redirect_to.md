### Added

- `permanent_redirect_to` in `fetch --json` output — the `Location` target of a permanent
  redirect (301/308), so CLI consumers can follow a 301 and update stored URLs without
  re-fetching. Present only when the response was a permanent redirect; absent on temporary
  redirects (302/303/307) and non-redirects, matching how `screenshot_b64` and `video_path`
  are emitted. ([#188](https://github.com/qte77/polyfetch-scrape/issues/188))
