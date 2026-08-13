# BRC Meshtastic ePaper Map — Makefile
# npm-style: `make install` sets up everything (venv + editable package + deps)

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
_VENV_FLAG := $(VENV)/.created

.PHONY: all install install-pi check-venv test test-full-mockup test-full-mockup-epaper calibrate run run-map test-screen pytest clean help

# ── default ────────────────────────────────────────────────────
all: pytest  ## run unit tests using the existing environment

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

# ── install for Raspberry Pi (uses system RPi.GPIO + spidev) ──
install-pi:  ## install with system Pi packages (avoids compiling from source)
	@echo "🔧 Creating virtual environment with system packages..."
	$(PYTHON) -m venv $(VENV) --system-site-packages
	$(VENV_PIP) install --upgrade pip setuptools wheel
	$(VENV_PIP) install -e ".[dev]"
	@echo ""
	@echo "✅ Installed! System RPi.GPIO and spidev are available."
	@echo "   Run 'make test-screen' to verify ePaper connection."
	@echo ""

# ── environment check (never installs dependencies) ───────────
check-venv:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "❌ Virtual environment not found. Run 'make install' or 'make install-pi' first."; \
		exit 1; \
	fi

# ── test / run ─────────────────────────────────────────────────
test: check-venv  ## run in --debug --screen mode (no hardware needed)
	$(VENV_PYTHON) display_map.py --debug --screen

test-full-mockup: check-venv  ## show map with 5–6 random mock people
	$(VENV_PYTHON) tools/full_mockup.py

test-full-mockup-epaper: check-venv  ## show populated mockup on E6 ePaper
	$(VENV_PYTHON) tools/full_mockup.py --epaper

calibrate: check-venv  ## launch calibration tool → http://localhost:8050
	$(VENV_PYTHON) calibrate.py

run: test  ## alias for test

run-map: check-venv  ## display the live map on ePaper and connect to Meshtastic
	$(VENV_PYTHON) display_map.py

# ── ePaper hardware test (Raspberry Pi only) ──────────────────
test-screen: check-venv  ## clear ePaper and draw test pattern
	$(VENV_PYTHON) tools/test_screen.py

# ── tests ──────────────────────────────────────────────────────
pytest: check-venv  ## run unit tests
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
