# Plan: `easter_hunt` contrib module (v0.1)

> Tracking: [#15](https://github.com/qte77/polyfetch-scrape/issues/15) · Branch: `feat/easter-hunt-v0.1`

## Context

`polyfetch-scrape` ships a typed `fetch(url) -> Response` with a 3-tier anti-bot
fallback. We want a downstream consumer that uses this API to scan fetched pages
for any notable artifact: recruiting hints (wakatime turtle), unusual HTTP
headers (P3P), `humans.txt`/`security.txt` presence, exposure of `.git`/`.env`,
etc. "Recruiting easter eggs" is one detector pack among many. Module name is
`easter_hunt` per design call.

Constraints:

- Strict TDD (Red-Green-Refactor) per detector
- Use public `fetch()` exclusively — no raw httpx
- Lives under `src/polyfetch_scrape/contrib/easter_hunt/`
- One-way import: nothing in core may import from `contrib/` (enforced by code
  review + naming convention; no test for it at v0.1)
- Coverage `fail_under=90` is global → new module ships ≥90% on day one

## Repo facts the plan respects

- `Response` (`src/polyfetch_scrape/response.py:6-13`) is frozen,
  `headers: Mapping[str,str]` (lowercased, duplicates collapsed
  last-write-wins — acceptable for P3P, documented limit).
- `fetch()` (`src/polyfetch_scrape/client.py:19-28`) supports `method="HEAD"`.
- CLI pattern (`src/polyfetch_scrape/cli.py:15-98`): single `typer.Typer(...)`
  app, `--json` flag. New subcommand mirrors style.
- `pyright` strict (`pyproject.toml:59-61`); ruff line-length 100; py311+.
- Mocking: `respx` (`tests/test_client.py`). Pure detectors take `Response`
  directly → no HTTP mock needed.
- `e2e` marker excludes real network from default `make test` and from
  coverage (`pyproject.toml:42-49`).
- `filterwarnings = ["error"]` (`pyproject.toml:44`).

## Target layout

```text
src/polyfetch_scrape/contrib/
  __init__.py                          # empty — opt-in import barrier
  easter_hunt/
    __init__.py                        # exports: hunt, Finding, DETECTORS
    finding.py                         # frozen Finding dataclass
    seeds.py                           # SEEDS, WELL_KNOWN_PATHS
    detectors.py                       # html_comments, weird_headers, wellknown_present
    hunt.py                            # orchestrator + literal-IP SSRF guard
tests/contrib/easter_hunt/
  fixtures/                            # added per test as needed (not pre-staged)
  test_detectors.py                    # all three detectors (one file until it grows)
  test_hunt.py                         # orchestrator with respx-mocked fetch
  test_cli.py                          # CliRunner — covers easter-hunt subcommand
  test_e2e_live.py                     # @pytest.mark.e2e — single seed, real net
```

CLI: extend the existing `polyfetch` typer app with a subcommand group, no new
`[project.scripts]` entry:

```bash
polyfetch easter-hunt scan https://wakatime.com/
polyfetch easter-hunt scan --seeds-file seeds.txt --json
polyfetch easter-hunt scan https://wakatime.com/ --include-wellknown
```

## Public surface (v0.1)

```python
# contrib/easter_hunt/finding.py
@dataclass(frozen=True, slots=True)
class Finding:
    detector: str          # "html_comments" | "weird_headers" | "wellknown_present"
    category: str          # "recruiting" | "policy" | "stack" | "novelty" | "exposure"
    severity: str          # "info" | "notable" | "warn"
    location: str          # "header:p3p" | "body:comment[3]" | "path:/.git/HEAD"
    snippet: str
    confidence: float      # 0.0–1.0
    url: str               # set inside detector from response.url

# contrib/easter_hunt/__init__.py
Detector = Callable[[Response], list[Finding]]
DETECTORS: tuple[Detector, ...] = (html_comments, weird_headers, wellknown_present)

# contrib/easter_hunt/hunt.py
def hunt(
    seeds: Iterable[str],
    *,
    paths: Iterable[str] = ("/",),
    detectors: Iterable[Detector] = DETECTORS,
    timeout: float = 10.0,
) -> list[Finding]: ...
```

Default `paths=("/",)`. Well-known sweep is opt-in via
`paths=("/",) + WELL_KNOWN_PATHS`.

## TDD slices

Each slice: write failing test → minimal impl → `make quick_validate` →
`make test`. Refactor only when a second consumer appears (AHA).

### Slice 1 — `html_comments` detector + inline extractor

- RED: empty body → `[]`
- RED: wakatime fixture (turtle ASCII) → 1 Finding,
  `detector="html_comments"`, `category="novelty"`, `confidence>=0.8` (driven
  by box-drawing-char density `[▄▓█▀╓╙]`), `url=response.url`
- RED: comment containing `hir|join|recruit|career` → `category="recruiting"`
- RED: IE conditional / GTM boilerplate comment → no Finding
- Inline regex for `<!--([\s\S]*?)-->`. No `kernel.py`, no `Comment`
  dataclass. Extract only when Slice 2 or later needs the same primitive.

### Slice 2 — `weird_headers` detector

- RED: only-boring-headers (`content-type`, `server`, `date`, `cache-control`,
  `etag`, `vary`) → `[]`
- RED: `p3p: "CP=..."` → 1 Finding, `category="policy"`,
  `severity="notable"`, `location="header:p3p"`
- RED: `x-clacks-overhead` → `category="novelty"`
- RED: `x-hire-me` → `category="recruiting"`
- Module docstring documents `Mapping[str,str]` collapse limit.

### Slice 3 — `wellknown_present` detector

- RED: response with `status=404` → `[]`
- RED: `path:/security.txt status=200` → `category="policy"`,
  `severity="info"`
- RED: `path:/.git/HEAD status=200` → `category="exposure"`,
  `severity="warn"`
- RED: `path:/.env status=200` → `category="exposure"`, `severity="warn"`
- `seeds.py` defines `WELL_KNOWN_PATHS` tuple: `/humans.txt`, `/robots.txt`,
  `/ads.txt`, `/security.txt`, `/.well-known/security.txt`,
  `/.well-known/dnt-policy.txt`, `/.well-known/change-password`,
  `/.well-known/gpc.json`, `/sitemap.xml`, `/manifest.json`, `/.git/HEAD`,
  `/.env`, `/404-not-a-real-page`.

### Slice 4 — orchestrator `hunt()` + literal-IP SSRF guard

- `respx` mocks fetch's httpx tier (mirror `tests/test_client.py`)
- RED: 2 seeds × 1 path × 3 detectors loop returns aggregated Findings
- RED: `FetchError` from one fetch is swallowed; loop continues
- RED: `http://127.0.0.1/`, `http://10.0.0.1/`, `http://169.254.0.1/` raise
  `ValueError` *before* any fetch (literal-IP check via
  `ipaddress.ip_address(host).is_private | .is_loopback | .is_link_local`)
- `_safe_fetch()` private helper swallows `FetchError`, returns `None`

### Slice 5 — `polyfetch easter-hunt scan` subcommand + e2e canary + governance

- New typer sub-`app`:
  `easter_hunt = typer.Typer(); app.add_typer(easter_hunt, name="easter-hunt")`.
  Single `scan` command mirrors `cli.py:fetch` (typer pattern, `--json` flag).
- CliRunner tests for: `scan <url>`, `scan --seeds-file <path> --json`,
  `scan <url> --include-wellknown`, invalid URL → exit 2.
- `@pytest.mark.e2e` test scans `https://wakatime.com/`, asserts at least one
  `category="novelty"` finding present (regression canary).
- `CHANGELOG.md` `## [Unreleased] ### Added` entry.
- One-line pointer in `README.md` under Project Outline: "Contrib modules in
  `src/polyfetch_scrape/contrib/` are unsupported extras."
- Conventional commit per slice: `feat(easter_hunt): <slice>`.

## Out of scope for v0.1

Listed so they don't sneak in:

- Detector packs `tracking`, `stack`, `secret-leak`, `seo`, `deprecated`,
  `hidden_css`, `console_banners` (JS bundle scan)
- DNS-based SSRF (resolve hostname → assert public IP). v0.1 is literal-IP
  only.
- `robots.txt` / crawl-delay enforcement
- Parallelism (`bulk --workers` integration)
- Image / P3P sweep at asset CDN level
- Hypothesis property tests
- Optional dep group `[project.optional-dependencies] easter-hunt = [...]` —
  v0.1 is stdlib-only (`re`, `ipaddress`)
- One-way-import guard test (convention enforced by code review)
- Per-module README

## Files modified / added

**New** (all under `src/polyfetch_scrape/contrib/easter_hunt/` and
`tests/contrib/easter_hunt/`): `contrib/__init__.py`,
`easter_hunt/__init__.py`, `easter_hunt/finding.py`,
`easter_hunt/seeds.py`, `easter_hunt/detectors.py`, `easter_hunt/hunt.py`,
plus 4 test files.

**Edited (small):**

- `src/polyfetch_scrape/cli.py` — `app.add_typer(...)` line for the
  `easter-hunt` subcommand (this is the one core file the contrib touches;
  OK because the import direction is still core → contrib at this single
  point, and removing the line cleanly disables the feature)
- `CHANGELOG.md` — `## [Unreleased] ### Added`
- `README.md` — one-line contrib pointer

**NOT edited:** `client.py`, `response.py`, `retry.py`, `errors.py`,
`__init__.py`, `_backends/*`. Core behavior unchanged.

Note: the `cli.py` edit is a deliberate exception to "core never imports
contrib". Acceptable because (a) it's one line, (b) wrapping in
`try/except ImportError` keeps core functional if `contrib/` is removed,
(c) it avoids the public `[project.scripts]` surface a separate binary would
create.

## Verification

After each slice:

```bash
make quick_validate     # ruff + pyright on src
make test               # unit tests, e2e excluded
```

Before declaring v0.1 done:

```bash
make validate           # ruff + pyright + complexipy + pytest --cov (>=90%)
make test_e2e           # the live wakatime canary
polyfetch easter-hunt scan https://wakatime.com/ --json | jq .   # smoke
```

Governance:

- `CHANGELOG.md` `## [Unreleased] ### Added` updated
- Conventional commits `feat(easter_hunt): ...` per slice
