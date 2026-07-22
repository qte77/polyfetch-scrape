### Added

- **`.claude/workflows/perf-cwv-pass.js`** — the estate-shared CWV perf pass (relocated here from
  fo-scraper-miwi by owner decision). It drives `make <target>` (default `perf_cwv`) in a consumer repo
  passed via `args.repo` (default: the current session repo) and, given `args.baseline`, returns a
  per-combo regression verdict. **No polyfetch coupling** — polyfetch only hosts the file; the contract
  is that the consumer's recipe writes `results/ui-check/<ts>_perf/metrics.json`
  (`{"<page>-<profile>": {fcp,lcp,cls,dcl,load,requests,bytes}}`). Reference implementation:
  fo-scraper-miwi `scripts/perf_cwv.py`.
