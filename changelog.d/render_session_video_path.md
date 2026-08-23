### Fixed

- `render_session`: recorded videos are no longer orphaned — `RenderSession.video_path` is now
  populated on teardown. The path was read after `playwright.stop()`, so `video.path()` raised
  against the stopped driver and the error was swallowed, leaving `video_path` as `None`. Teardown
  now closes the context, reads the path while the driver is still alive (unsuppressed), then
  closes the browser and stops the driver in a `finally` block.
  ([#199](https://github.com/qte77/polyfetch-scrape/issues/199))
