export const meta = {
  name: 'perf-cwv-pass',
  description: 'Measure CWV medians (FCP/LCP/CLS/bytes) for a repo web UI on its local serve; optionally compare vs a baseline for a regression verdict',
  whenToUse: 'Estate-shared perf pass (hosted here; no polyfetch coupling — it only drives `make <target>` in a consumer repo). args: {repo} absolute path of the checkout to measure (default: the current session repo); {make_target} recipe name (default `perf_cwv`); {baseline} a prior metrics.json object for a per-combo regression verdict (omit to just record a fresh baseline). CONTRACT: the recipe writes results/ui-check/<ts>_perf/metrics.json shaped {"<page>-<profile>": {fcp,lcp,cls,dcl,load,requests,bytes}}. Reference implementation: fo-scraper-miwi scripts/perf_cwv.py.',
  phases: [
    { title: 'Measure', detail: 'make <target> (cold-cache median runs) in the target repo' },
    { title: 'Compare', detail: 'current vs args.baseline -> regression verdict' },
  ],
}

// Shape of the contract metrics.json: {"<page>-<profile>": {fcp,lcp,cls,dcl,load,requests,bytes}}
const METRICS = {
  type: 'object',
  additionalProperties: {
    type: 'object',
    properties: {
      fcp: { type: 'number' },
      lcp: { type: 'number' },
      cls: { type: 'number' },
      dcl: { type: 'number' },
      load: { type: 'number' },
      requests: { type: 'number' },
      bytes: { type: 'number' },
    },
    required: ['fcp', 'lcp', 'cls', 'bytes'],
  },
}

const repo = (args && args.repo) || null
const target = (args && args.make_target) || 'perf_cwv'
const where = repo
  ? 'In ' + repo + ' '
  : 'In the current working repository (the session cwd) '

phase('Measure')
const current = await agent(
  where +
    'run `make ' +
    target +
    '`. If it fails because a patchright/playwright browser is missing, run the repo browser-setup ' +
    'recipe once (e.g. `make e2e_setup` or `make setup_browsers`) and retry. The run serves the UI ' +
    'locally and writes median metrics to results/ui-check/<ts>_perf/metrics.json. Read that ' +
    'metrics.json from the NEWEST *_perf run dir and return its parsed JSON object verbatim ' +
    '(no commentary).',
  { label: 'measure', schema: METRICS },
)

if (!args || !args.baseline) {
  log('no baseline passed — recording a fresh baseline only')
  return { current, verdict: 'baseline-recorded' }
}

phase('Compare')
const VERDICT = {
  type: 'object',
  properties: {
    regressions: { type: 'array', items: { type: 'string' } },
    improvements: { type: 'array', items: { type: 'string' } },
    ok: { type: 'boolean' },
  },
  required: ['regressions', 'improvements', 'ok'],
}
const verdict = await agent(
  'Compare these CWV medians per combo+metric. CURRENT: ' +
    JSON.stringify(current) +
    ' BASELINE: ' +
    JSON.stringify(args.baseline) +
    '. Flag a REGRESSION when current is worse than baseline by BOTH >10% and >50ms (for timing ' +
    'metrics) or by >5% (for bytes/requests); list improvements of the same magnitude. Small jitter ' +
    'is not a finding. ok=true when there are no regressions. Return only the structured result.',
  { label: 'compare', schema: VERDICT },
)
return { current, verdict }
