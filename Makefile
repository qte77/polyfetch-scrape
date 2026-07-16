.PHONY: setup_uv setup_dev setup_browsers doctor lint_src lint_tests type_check complexity \
        test test_e2e test_coverage validate ci quick_validate probe probe_bulk hunt \
        discover demo_tiers render screencast changelog_new changelog_preview changelog_release help
.DEFAULT_GOAL := help


# MARK: SETUP


setup_uv:  ## Install uv and sync frozen deps (bootstrap-only pip usage)
	pip install uv -q
	uv sync --frozen

setup_dev:  ## Sync dev deps via uv
	uv sync

setup_browsers:  ## Install Patchright Chromium binary (~300MB; required for e2e)
	uv run patchright install chromium

doctor:  ## Check the browser-tier Chromium is installed; install it if missing
	uv run polyfetch doctor --fix


# MARK: QUALITY


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

ci:  ## Check-only CI pipeline (no mutation; validate without the formatters)
	uv run ruff format --check .
	uv run ruff check .
	$(MAKE) -s type_check
	$(MAKE) -s complexity
	$(MAKE) -s test_coverage
	@echo "=== ci: all passed ==="

quick_validate:  ## Fast dev cycle (no tests)
	$(MAKE) -s lint_src
	$(MAKE) -s type_check
	@echo "=== quick_validate: all passed ==="


# MARK: CHANGELOG


changelog_new:  ## Add + stage a scriv changelog fragment for this PR
	uv run scriv create --add

changelog_preview:  ## Preview the assembled release entry from changelog.d/
	uv run scriv print

changelog_release:  ## Collect fragments into CHANGELOG.md. Usage: make changelog_release VERSION=X.Y.Z
	@if [ -z "$(VERSION)" ]; then echo "Error: VERSION required. Usage: make changelog_release VERSION=X.Y.Z"; exit 2; fi
	uv run scriv collect --version "$(VERSION)"


# MARK: APP


# Only treat probe/probe_bulk flag vars as user-supplied when they come from
# the command line, not from the environment (e.g. shell BROWSER=...).
_cli = $(filter command\ line file,$(origin $(1)))

probe:  ## Probe a single URL. Usage: make probe URL=https://... [JSON=1] [BROWSER=chrome|firefox] [MAX_ATTEMPTS=N]
	@if [ -z "$(URL)" ]; then echo "Error: URL required. Usage: make probe URL=https://example.com"; exit 1; fi
	uv run polyfetch fetch "$(URL)" \
		$(if $(call _cli,JSON),--json) \
		$(if $(call _cli,BROWSER),--browser $(BROWSER)) \
		$(if $(call _cli,MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS))

probe_bulk:  ## Probe URLs from FILE. Usage: make probe_bulk FILE=urls.txt [WORKERS=N] [TEXT=1] [MAX_ATTEMPTS=N]
	@if [ -z "$(FILE)" ]; then echo "Error: FILE required. Usage: make probe_bulk FILE=urls.txt"; exit 1; fi
	uv run polyfetch bulk "$(FILE)" \
		$(if $(call _cli,WORKERS),--workers $(WORKERS)) \
		$(if $(call _cli,MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS)) \
		$(if $(call _cli,TEXT),--text)


discover:  ## Discover structured entrypoints (sitemaps/feeds/llms.txt/JSON-LD). Usage: make discover URL=https://... [JSON=1]
	@if [ -z "$(URL)" ]; then echo "Error: URL required. Usage: make discover URL=https://example.com"; exit 1; fi
	uv run polyfetch discover "$(URL)" \
		$(if $(call _cli,JSON),--json)


SEEDS ?= examples/easter-hunt-seeds.txt

hunt:  ## Scan for page artifacts. Usage: make hunt [URL=https://...] [SEEDS=file] [JSON=1] [WELLKNOWN=1]
	uv run polyfetch easter-hunt scan \
		$(if $(URL),"$(URL)",--seeds-file "$(SEEDS)") \
		$(if $(call _cli,JSON),--json) \
		$(if $(call _cli,WELLKNOWN),--include-wellknown)


demo_tiers:  ## Exemplify all 3 fallback tiers: httpx/curl_cffi JA3 diff + patchright render+shot
	uv run python examples/fallback_tiers_demo.py


render:  ## Render a dynamic page + screenshot, with device/color-scheme emulation + video recording, via Patchright. Usage: make render [URL=https://...] [OUT=dir] [DEVICE=name] [COLOR_SCHEME=light|dark] [VIDEO_OUT=dir]
	uv run python examples/render_screenshot.py \
		$(if $(URL),"$(URL)") \
		$(if $(call _cli,OUT),--out-dir "$(OUT)") \
		$(if $(call _cli,DEVICE),--device "$(DEVICE)") \
		$(if $(call _cli,COLOR_SCHEME),--color-scheme $(COLOR_SCHEME)) \
		$(if $(call _cli,VIDEO_OUT),--video-out "$(VIDEO_OUT)")


screencast:  ## Record the README navigation screencast GIF (render_session walkthrough). Usage: make screencast [OUT=path]
	uv run --with pillow python examples/navigate_screencast.py \
		$(if $(call _cli,OUT),--out "$(OUT)")


# MARK: HELP


help:  ## Show available recipes grouped by section
	@echo "Usage: make [recipe]"
	@echo ""
	@awk '/^# MARK:/ { \
		section = substr($$0, index($$0, ":")+2); \
		printf "\n\033[1m%s\033[0m\n", section \
	} \
	/^[a-zA-Z0-9_-]+:.*?##/ { \
		helpMessage = match($$0, /## (.*)/); \
		if (helpMessage) { \
			recipe = $$1; \
			sub(/:/, "", recipe); \
			printf "  \033[36m%-16s\033[0m %s\n", recipe, substr($$0, RSTART + 3, RLENGTH) \
		} \
	}' $(MAKEFILE_LIST)
