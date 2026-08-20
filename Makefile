# BRC Meshtastic ePaper Map — Makefile
# npm-style: `make install` sets up everything (venv + editable package + deps)

PYTHON := python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
MESHTASTIC_CLI := $(VENV)/bin/meshtastic
_VENV_FLAG := $(VENV)/.created
HISTORY_DATABASE ?=
HISTORY_DATABASE_ARG = $(if $(strip $(HISTORY_DATABASE)),--database "$(HISTORY_DATABASE)",)
MESH_DEVICE ?=
MESH_DEVICE_ARG = $(if $(strip $(MESH_DEVICE)),--port "$(MESH_DEVICE)",)
MESH_LOCATION_FIELDS := user.longName,user.id,user.shortName,position.latitude,position.longitude,position.altitude,lastHeard,since
WEATHER_ALERTS ?= 1
WEATHER_ALERTS_ARG = $(if $(filter 1 true yes on,$(strip $(WEATHER_ALERTS))),--weather-alerts,--no-weather-alerts)
MESH_HISTORY_OUTPUT ?= mesh-history.csv
CONVERSATIONS_OUTPUT ?= conversations.csv
BLE_ENV_FILE ?= .env
BLE_APPLY ?= 0
BLE_APPLY_ARG = $(if $(filter 1 true yes on,$(strip $(BLE_APPLY))),--apply,)
ADMIN_SERIAL_DEVICE ?=
ADMIN_SERIAL_DEVICE_ARG = $(if $(strip $(ADMIN_SERIAL_DEVICE)),--serial-device "$(ADMIN_SERIAL_DEVICE)",)

.PHONY: all install install-pi check-venv test test-full-mockup test-full-mockup-epaper calibrate run run-map mesh-locations mesh-ble-scan mesh-ble-config mesh-admin-pull-keys mesh-admin-audit mesh-admin-enroll logs dump-mesh-history dump-conversations test-screen pytest clean help

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

test-full-mockup: check-venv  ## show burners across streets, non-city areas, and trash fence
	$(VENV_PYTHON) tools/full_mockup.py

test-full-mockup-epaper: check-venv  ## refresh moving mock burners every minute
	$(VENV_PYTHON) tools/full_mockup.py --epaper --interval 60

calibrate: check-venv  ## launch calibration tool → http://localhost:8050
	$(VENV_PYTHON) calibrate.py

run: test  ## alias for test

run-map: check-venv  ## display the live map on ePaper and connect to Meshtastic
	$(VENV_PYTHON) display_map.py $(WEATHER_ALERTS_ARG)

mesh-locations: check-venv  ## compare radio NodeDB with map-retained locations
	@echo "Radio NodeDB (not channel-specific); N/A means the CLI did not expose that field."
	$(MESHTASTIC_CLI) $(MESH_DEVICE_ARG) --nodes --show-fields $(MESH_LOCATION_FIELDS)
	@echo ""
	$(VENV_PYTHON) tools/show_latest_locations.py $(HISTORY_DATABASE_ARG)

mesh-ble-scan: check-venv  ## list nearby Meshtastic BLE radios
	$(VENV_PYTHON) tools/configure_ble_nodes.py --scan

mesh-ble-config: check-venv  ## audit BLE radios; set BLE_APPLY=1 to repair and verify
	$(VENV_PYTHON) tools/configure_ble_nodes.py --env-file "$(BLE_ENV_FILE)" $(BLE_APPLY_ARG)

mesh-admin-pull-keys: check-venv  ## collect the BLE/USB controller public keys into .env
	$(VENV_PYTHON) tools/manage_admin_keys.py --env-file "$(BLE_ENV_FILE)" $(ADMIN_SERIAL_DEVICE_ARG) pull

mesh-admin-audit: check-venv  ## audit both PKI administrator keys across the BLE fleet
	$(VENV_PYTHON) tools/manage_admin_keys.py --env-file "$(BLE_ENV_FILE)" audit

mesh-admin-enroll: check-venv  ## enroll both PKI administrator keys and verify every radio
	$(VENV_PYTHON) tools/manage_admin_keys.py --env-file "$(BLE_ENV_FILE)" enroll

logs:  ## show the latest systemd map logs
	journalctl -u brc-meshtastic-map.service -n 100 --no-pager

# ── history exports ────────────────────────────────────────────
dump-mesh-history: check-venv  ## export all recorded positions to mesh-history.csv
	$(VENV_PYTHON) tools/export_history.py positions $(HISTORY_DATABASE_ARG) --output "$(MESH_HISTORY_OUTPUT)"

dump-conversations: check-venv  ## export all received chats to conversations.csv
	$(VENV_PYTHON) tools/export_history.py conversations $(HISTORY_DATABASE_ARG) --output "$(CONVERSATIONS_OUTPUT)"

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
