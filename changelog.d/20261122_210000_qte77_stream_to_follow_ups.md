<!--
A new scriv changelog fragment.

Uncomment the section that is right (remove the HTML comment wrapper).
For top level release notes, leave all the headers commented out.
-->

### Changed

- `fetch --output FILE --json` on an unfollowed redirect or a `304` keeps its summary
  fields and now adds `"error_type": "NotSaved"` and a `"message"` with the reason also
  printed to stderr (exit `1`, as before).

### Fixed

- `fetch(stream_to=...)` flushes the temp file to disk (`fsync`) before moving it onto the
  target, and reports a failure to remove the temp file as a `FetchError` like any other
  disk error, unless another error is already being raised: a failed temp-file removal then
  leaves that error as it is (a transport error stays retryable, an interrupt stays an
  interrupt). A failed close of the temp file can still replace it, as before. A symlinked target is replaced by a regular file, its referent untouched
  (documented).
- A streamed curl_cffi fetch with `timeout=0` now means no whole-transfer limit, as a
  buffered one does, instead of a 1 ms libcurl timeout. A negative `timeout` still fails on
  both.
