# BRC Meshtastic ePaper Map — Makefile
# npm-style: `make install` sets up everything (venv + editable package + deps)

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
_VENV_FLAG := $(VENV)/.created

.PHONY: all install test calibrate run clean help

# ── default ────────────────────────────────────────────────────
all: install test  ## set up venv, install deps, run test

# ── install (npm-style: single command to set up everything) ───
install: $(_VENV_FLAG)  ## create venv and install all dependencies
	@echo "📦 Installing dependencies (editable mode)..."
	$(VENV_PIP) install -e ".[dev]"
	@echo ""
	@echo "✅ Installed! Run 'make test' or 'make calibrate'"
	@echo ""

$(_VENV_FLAG):
	@echo "🔧 Creating virtual environment..."
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip setuptools wheel
	@touch $(_VENV_FLAG)

# ── install for Raspberry Pi (includes RPi.GPIO + spidev) ──────
install-pi: $(_VENV_FLAG)  ## install with Pi-specific hardware deps
	$(VENV_PIP) install -e ".[dev,pi]"

# ── test / run ─────────────────────────────────────────────────
test: install  ## run in --debug --screen mode (no hardware needed)
	$(VENV_PYTHON) display_map.py --debug --screen

calibrate: install  ## launch calibration tool → http://localhost:8050
	$(VENV_PYTHON) calibrate.py

run: test  ## alias for test

# ── ePaper hardware test (Raspberry Pi only) ──────────────────
test-screen: install  ## clear ePaper and draw test pattern
	$(VENV_PYTHON) tools/test_screen.py

# ── tests ──────────────────────────────────────────────────────
pytest: install  ## run unit tests
	$(VENV_PYTHON) -m pytest tests/ -v

# ── clean ──────────────────────────────────────────────────────
clean:  ## remove venv, caches, and build artifacts
	rm -rf $(VENV) .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf '{}' + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf '{}' + 2>/dev/null || true

# ── help ───────────────────────────────────────────────────────
help:  ## show this help
	@echo "Usage: make [target]"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
