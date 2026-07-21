### Added

- `full_page` screenshot target on the patchright tier — `--screenshot full_page`,
  `RenderOptions(screenshot="full_page")`, and `Screenshot(target="full_page")` capture the
  whole scrollable page. Previously disabled because older patchright wrote 0 bytes on tall
  pages; re-enabled after verifying patchright 1.61.2 writes the full image. On an
  `is_mobile` emulated device the capture clips to the viewport rather than scrolling.
  ([#132](https://github.com/qte77/polyfetch-scrape/issues/132))
