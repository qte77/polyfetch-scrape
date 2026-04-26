.PHONY: setup_uv setup_dev lint_src lint_tests type_check complexity \
        test test_coverage validate quick_validate help
.DEFAULT_GOAL := help

setup_uv:  ## Install uv and sync frozen deps (bootstrap-only pip usage)
	pip install uv -q
	uv sync --frozen

setup_dev:  ## Sync dev deps via uv
	uv sync

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

test:  ## Run all tests (verbose)
	uv run pytest -vv --tb=short

test_coverage:  ## Run tests with coverage threshold (verbose)
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

help:  ## Show recipes
	@awk '/^[a-zA-Z0-9_-]+:.*?##/ { sub(/:/,"",$$1); printf "  \033[36m%-16s\033[0m %s\n", $$1, substr($$0, index($$0,"## ")+3) }' $(MAKEFILE_LIST)
