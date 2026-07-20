# Makefile — Single Shot AAS v2
# Usage: make <target>
# Requires: venv activated OR run with PYTHON=python3

PYTHON      := python3
PIP         := pip3
SRC         := .
VENV        := venv
VENV_ACT    := source $(VENV)/bin/activate
FLASK_APP   := web_app.app:create_app()
FLASK_RUN   := FLASK_APP="$(FLASK_APP)" FLASK_ENV=development
PORT        := 5000

.PHONY: help setup install lint test test-unit run web voice clean login

# ── Default ───────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Single Shot AAS — Available Commands"
	@echo "  ════════════════════════════════════"
	@echo "  make setup      — Full first-time setup (venv + deps + dirs)"
	@echo "  make install    — Install/update Python dependencies only"
	@echo "  make run        — Start web app (http://localhost:$(PORT))"
	@echo "  make web        — Alias for 'make run'"
	@echo "  make voice      — Start in voice-trigger mode"
	@echo "  make login      — Open browser OAuth login flow"
	@echo "  make test       — Run all unit tests"
	@echo "  make test-unit  — Run unit tests with verbose output"
	@echo "  make lint       — Run flake8 linter"
	@echo "  make clean      — Remove __pycache__ and .pytest_cache"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
setup:
	bash setup.sh

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# ── Run Modes ────────────────────────────────────────────────────────────────
run web:
	$(PYTHON) main.py --web

voice:
	$(PYTHON) main.py --voice

# ── OAuth Login ──────────────────────────────────────────────────────────────
login:
	@echo "Starting web app for login..."
	@echo "Opening http://localhost:$(PORT)/auth/google"
	@( sleep 2 && xdg-open "http://localhost:$(PORT)/auth/google" 2>/dev/null || \
	   open "http://localhost:$(PORT)/auth/google" 2>/dev/null || \
	   echo "  ► Open this URL in your browser: http://localhost:$(PORT)/auth/google" ) &
	$(PYTHON) main.py --web

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -q --tb=short

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v --tb=long

test-cov:
	$(PYTHON) -m pytest tests/ --cov=. --cov-report=html -q
	@echo "Coverage report: htmlcov/index.html"

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	$(PYTHON) -m flake8 . \
	  --exclude=venv,.venv,__pycache__,*.egg-info \
	  --max-line-length=120 \
	  --ignore=E501,W503

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name "__pycache__" -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Clean done."
