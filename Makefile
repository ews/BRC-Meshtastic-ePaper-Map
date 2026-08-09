# BRC Meshtastic ePaper Map — Makefile
# For development/testing on a laptop (no ePaper, no Meshtastic radio)

PYTHON := python3
PIP := $(PYTHON) -m pip
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: all venv install test clean help

all: venv install test  ## (default) set up venv, install deps, run test

# ─── virtualenv ────────────────────────────────────────────────
venv: $(VENV)/bin/activate

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip setuptools wheel

# ─── install dependencies ──────────────────────────────────────
install: venv
	$(VENV_PIP) install -r requirements-dev.txt

# ─── test / run ────────────────────────────────────────────────
test: venv install  ## Run in --debug --screen mode (no hardware needed)
	$(VENV_PYTHON) display_map.py --debug --screen

calibrate: venv install  ## Launch web-based calibration tool (http://localhost:8050)
	$(VENV_PYTHON) calibrate.py

run: test  ## Alias for test

# ─── clean ─────────────────────────────────────────────────────
clean:  ## Remove venv, caches, and generated files
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

# ─── help ──────────────────────────────────────────────────────
help:  ## Show this help
	@echo "Usage: make [target]"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
