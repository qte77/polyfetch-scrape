### Changed

- `USING.md` documents the `PLAYWRIGHT_BROWSERS_PATH` environment variable: it relocates the
  browser-tier Chromium cache off a tight `~/.cache` volume, and must be set for both
  `polyfetch doctor --fix` and runs. It also says to re-run `doctor --fix` after a patchright
  upgrade. `CONTRIBUTING.md` points to it from `make doctor`.
