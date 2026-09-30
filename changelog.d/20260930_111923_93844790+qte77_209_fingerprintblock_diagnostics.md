<!--
A new scriv changelog fragment.

Uncomment the section that is right (remove the HTML comment wrapper).
For top level release notes, leave all the headers commented out.
-->

### Added

- `FetchError` (and its subclasses, including the internal `FingerprintBlock`) now carries
  bounded diagnostics for the final tier's blocked or exhausted response: `headers`
  (`Set-Cookie` always redacted) and `body_excerpt` (truncated to 2 KB, decoded lossily).
  `fetch --json`'s error payload mirrors these as optional `headers`/`body_excerpt` keys,
  present only when captured.
  ([#209](https://github.com/qte77/polyfetch-scrape/issues/209))

<!--
### Changed

- A bullet item for the Changed category.

-->
<!--
### Deprecated

- A bullet item for the Deprecated category.

-->
<!--
### Removed

- A bullet item for the Removed category.

-->
<!--
### Fixed

- A bullet item for the Fixed category.

-->
<!--
### Security

- A bullet item for the Security category.

-->
