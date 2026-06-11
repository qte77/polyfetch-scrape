.PHONY: setup_uv setup_dev setup_browsers lint_src lint_tests type_check complexity \
        test test_e2e test_coverage validate quick_validate probe probe_bulk hunt help
.DEFAULT_GOAL := help

setup_uv:  ## Install uv and sync frozen deps (bootstrap-only pip usage)
	pip install uv -q
	uv sync --frozen

setup_dev:  ## Sync dev deps via uv
	uv sync

setup_browsers:  ## Install Patchright Chromium binary (~300MB; required for e2e)
	uv run patchright install chromium

lint_src:  ## Format + lint src with ruff
	uv run ruff format --exclude tests
	uv run ruff check --fix --exclude tests

lint_tests:  ## Format + lint tests with ruff
	uv run ruff format tests
	uv run ruff check --fix tests

type_check:  ## Static type check with pyright
	uv run pyright src

complexity:  ## Cognitive complexity with complexipy
	uv run complexipy -q .

test:  ## Run unit tests (verbose; e2e skipped by default)
	uv run pytest -vv --tb=short

test_e2e:  ## Run e2e tests against real network endpoints
	uv run pytest -vv --tb=short -m e2e --no-cov

test_coverage:  ## Run unit tests with coverage threshold (verbose)
	uv run pytest -vv --tb=short --cov --cov-report=term-missing

validate:  ## Full pre-commit validation
	$(MAKE) -s lint_src
	$(MAKE) -s lint_tests
	$(MAKE) -s type_check
	$(MAKE) -s complexity
	$(MAKE) -s test_coverage
	@echo "=== validate: all passed ==="

quick_validate:  ## Fast dev cycle (no tests)
	$(MAKE) -s lint_src
	$(MAKE) -s type_check
	@echo "=== quick_validate: all passed ==="

# Only treat probe/probe_bulk flag vars as user-supplied when they come from
# the command line, not from the environment (e.g. shell BROWSER=...).
_cli = $(filter command\ line file,$(origin $(1)))

probe:  ## Probe a single URL. Usage: make probe URL=https://... [JSON=1] [BROWSER=chrome|firefox] [MAX_ATTEMPTS=N]
	@if [ -z "$(URL)" ]; then echo "Error: URL required. Usage: make probe URL=https://example.com"; exit 1; fi
	uv run polyfetch fetch "$(URL)" \
		$(if $(call _cli,JSON),--json) \
		$(if $(call _cli,BROWSER),--browser $(BROWSER)) \
		$(if $(call _cli,MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS))

probe_bulk:  ## Probe URLs from FILE. Usage: make probe_bulk FILE=urls.txt [WORKERS=N] [TEXT=1]
	@if [ -z "$(FILE)" ]; then echo "Error: FILE required. Usage: make probe_bulk FILE=urls.txt"; exit 1; fi
	uv run polyfetch bulk "$(FILE)" \
		$(if $(call _cli,WORKERS),--workers $(WORKERS)) \
		$(if $(call _cli,TEXT),--text)

SEEDS ?= examples/easter-hunt-seeds.txt

hunt:  ## Scan for page artifacts. Usage: make hunt [URL=https://...] [SEEDS=file] [JSON=1] [WELLKNOWN=1]
	uv run polyfetch easter-hunt scan \
		$(if $(URL),"$(URL)",--seeds-file "$(SEEDS)") \
		$(if $(call _cli,JSON),--json) \
		$(if $(call _cli,WELLKNOWN),--include-wellknown)

help:  ## Show recipes
	@awk '/^[a-zA-Z0-9_-]+:.*?##/ { sub(/:/,"",$$1); printf "  \033[36m%-16s\033[0m %s\n", $$1, substr($$0, index($$0,"## ")+3) }' $(MAKEFILE_LIST)
