<!--
A new scriv changelog fragment.

Uncomment the section that is right (remove the HTML comment wrapper).
For top level release notes, leave all the headers commented out.
-->

### Added

- `render_session(...)` / `RenderOptions` accept `storage_state` (a saved
  storage-state JSON path or the equivalent mapping) and `extra_http_headers`,
  both applied at `new_context()` time, so a session can start authenticated.
- `RenderSession.save_storage_state(path)` writes the live context's cookies +
  localStorage back out for reuse on the next run; new "Authenticated session"
  recipe in `docs/scripting.md`.
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
