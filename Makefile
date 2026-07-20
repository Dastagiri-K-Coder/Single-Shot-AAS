# =============================================================================
#  Makefile — AI Attendance System developer commands
#
#  Usage:
#      make help      → list all targets
#      make setup     → first-time setup (calls setup.sh)
#      make run       → start web dashboard
#      make test      → run test suite
#      make lint      → lint + format check
#      make fmt       → auto-format code
# =============================================================================

SHELL       := /bin/bash
SRC         := face recognition source code
VENV        := .venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
PYTEST      := $(VENV)/bin/pytest
RUFF        := $(VENV)/bin/ruff
BLACK       := $(VENV)/bin/black
PRECOMMIT   := $(VENV)/bin/pre-commit

.DEFAULT_GOAL := help

# ── Phony targets ─────────────────────────────────────────────────────────────
.PHONY: help setup install install-dev run enroll preview voice test lint fmt \
        fmt-check clean nuke hooks check-env validate-env

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  🎓 AI Attendance System — Make Targets"
	@echo "  ──────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
setup: ## 🚀 First-time dev setup (venv, deps, .env, pre-commit)
	@chmod +x setup.sh && bash setup.sh

install: ## 📦 Install production dependencies into .venv
	@test -d $(VENV) || python3.10 -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r "$(SRC)/requirements.txt"

install-dev: install ## 📦 Install dev dependencies (testing, linting)
	$(PIP) install -r requirements-dev.txt

hooks: ## 🎣 Install pre-commit hooks
	$(PRECOMMIT) install
	$(PRECOMMIT) install --hook-type commit-msg
	@echo "✅ Pre-commit hooks installed"

# ── Running ───────────────────────────────────────────────────────────────────
run: check-env ## 🌐 Start Flask web dashboard (http://localhost:5000)
	cd "$(SRC)" && $(PYTHON) main.py --web

voice: check-env ## 🎤 Start voice trigger mode
	cd "$(SRC)" && $(PYTHON) main.py --voice

preview: check-env ## 👁️  Start camera preview mode
	cd "$(SRC)" && $(PYTHON) main.py --preview

enroll: check-env ## 👤 Enroll a student — usage: make enroll NAME="John Doe"
ifndef NAME
	@echo "Usage: make enroll NAME=\"Student Full Name\""
	@exit 1
endif
	cd "$(SRC)" && $(PYTHON) main.py --enroll "$(NAME)"

# ── Testing ───────────────────────────────────────────────────────────────────
test: ## 🧪 Run full test suite with coverage
	$(PYTEST) tests/ -v --tb=short \
		--cov="$(SRC)" \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--cov-fail-under=60

test-fast: ## ⚡ Run tests without coverage (faster)
	$(PYTEST) tests/ -v --tb=short -x

test-unit: ## 🔬 Run unit tests only
	$(PYTEST) tests/unit/ -v

test-integration: ## 🔗 Run integration tests only
	$(PYTEST) tests/integration/ -v

# ── Linting & Formatting ──────────────────────────────────────────────────────
lint: ## 🔍 Run all linters (ruff + bandit)
	$(RUFF) check "$(SRC)/" tests/
	@echo "✅ Ruff passed"
	$(VENV)/bin/bandit -r "$(SRC)/" -c pyproject.toml --severity-level medium || true

fmt: ## 🎨 Auto-format all code (ruff + black)
	$(RUFF) check --fix "$(SRC)/" tests/
	$(BLACK) "$(SRC)/" tests/
	@echo "✅ Formatting applied"

fmt-check: ## ✅ Check formatting without modifying files (for CI)
	$(RUFF) check "$(SRC)/" tests/
	$(BLACK) --check "$(SRC)/" tests/

# ── Environment validation ────────────────────────────────────────────────────
check-env: ## 🔑 Check that .env file exists
	@test -f "$(SRC)/.env" || \
		(echo "❌  Missing: $(SRC)/.env — run: cp '$(SRC)/.env.example' '$(SRC)/.env'" && exit 1)

validate-env: ## ✅ Validate all .env keys match .env.example
	@echo "Validating .env against .env.example ..."
	@missing=0; \
	while IFS= read -r line; do \
		[[ "$$line" =~ ^#.*$$ || -z "$$line" ]] && continue; \
		key="$${line%%=*}"; \
		grep -q "^$${key}=" "$(SRC)/.env" || { echo "  ❌ Missing: $$key"; missing=1; }; \
	done < "$(SRC)/.env.example"; \
	[[ $$missing -eq 0 ]] && echo "✅ All .env keys present." || exit 1

# ── Housekeeping ──────────────────────────────────────────────────────────────
clean: ## 🧹 Remove __pycache__ and .pyc files
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path "./.venv/*" -delete 2>/dev/null || true
	find . -name "*.pyo" -not -path "./.venv/*" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage
	@echo "✅ Cleaned"

nuke: ## 💥 Full reset: remove .venv and all caches
	$(MAKE) clean
	rm -rf .venv/
	@echo "✅ Full reset complete. Run: make setup"
