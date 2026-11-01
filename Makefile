# Single entry point for local dev and CI. `make check` is exactly what CI runs.
SHELL := /bin/bash
VENV  := backend/.venv
PY    := $(VENV)/bin/python
BE    := cd backend && . .venv/bin/activate &&
FE    := cd frontend &&

.DEFAULT_GOAL := help
.PHONY: help setup dev test test-be test-fe cov lint fmt typecheck audit deadcode check ci hooks clean

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## create venv, install backend + frontend deps
	cd backend && (test -d .venv || uv venv --python 3.12) && . .venv/bin/activate && uv pip install -r requirements-dev.txt
	$(FE) npm ci

dev: ## hot-reload Flask + Vite
	./dev.sh

test-be:
	$(BE) pytest -q -n auto
test-fe:
	$(FE) npm run test --silent
test: test-be test-fe ## run all tests

cov: ## tests with coverage thresholds
	$(BE) pytest -q -n auto --cov --cov-report=term:skip-covered --cov-report=xml
	$(FE) npm run test:cov --silent

lint: ## ruff + eslint + format checks
	$(BE) ruff check . && ruff format --check .
	$(FE) npm run lint --silent && npm run format:check --silent

fmt: ## auto-format everything
	$(BE) ruff check . --fix && ruff format .
	$(FE) npm run format --silent

typecheck: ## mypy + tsc
	$(BE) mypy .
	$(FE) npm run typecheck --silent

audit: ## security scans (bandit, pip-audit, npm audit; hadolint/gitleaks/trivy when installed)
	$(BE) bandit -q -r . -c pyproject.toml --severity-level medium
	$(BE) pip-audit -r requirements.txt --progress-spinner off
	$(FE) npm run audit --silent
	@command -v hadolint >/dev/null && hadolint backend/Dockerfile frontend/Dockerfile || echo 'hadolint not installed: skipped (brew install hadolint)'
	@command -v gitleaks >/dev/null && gitleaks detect --no-banner --redact || echo 'gitleaks not installed: skipped (brew install gitleaks)'
	@command -v trivy >/dev/null && trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 --skip-dirs backend/.venv,frontend/node_modules . || echo 'trivy not installed: skipped (brew install trivy)'

deadcode: ## vulture + knip (advisory)
	-$(BE) vulture . --min-confidence 80 --exclude .venv,tests,alembic
	-$(FE) npm run deadcode --silent

check: lint typecheck cov audit ## what CI runs
	$(FE) npm run build --silent

ci: check

hooks: ## install git pre-commit hooks
	$(VENV)/bin/pre-commit install --install-hooks
	$(VENV)/bin/pre-commit install --hook-type pre-push

clean:
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/htmlcov backend/.coverage frontend/dist frontend/coverage
