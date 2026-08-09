# Improvement Plan

## Phase 1: Bug Fixes ✅ (completed)

All known runtime bugs fixed and committed.

| # | Bug | File | Severity | Status |
| --- | --- | --- | --- | --- |
| 1 | `MAN_LAT = 40.783242,` — trailing comma makes it a tuple | `config.py` | Critical | ✅ |
| 2 | `new[burgner]` typo → `NameError` | `display_map.py` | Critical | ✅ |
| 3 | `distance_ft()` called with latitude twice | `display_map.py` | High | ✅ |
| 4 | Malformed tuple in `shape_man_vertical` | `display_map.py` | Critical | ✅ |
| 5 | README references wrong filename | `README.org` | Low | ✅ |
| 6 | Global fd never flushed/closed | `config.py` + `display_map.py` | High | ✅ |
| 7 | `equal_bm_coordinates` misses node join/leave | `display_map.py` | Medium | ✅ |
| 8 | Red layer never cleared → ghosting | `display_map.py` | Medium | ✅ |
| 9 | `interface.close()` dead code, no graceful shutdown | `display_map.py` | Medium | ✅ |

---

## Phase 2: Architecture & Robustness ✅ (completed)

### 2.1 Connection resilience ✅

- Added `connect_mesh_serial()` / `connect_mesh_tcp()` with exponential backoff (5s→120s, 2× factor)
- `get_mesh_info()` retries on transient poll failures

### 2.2 Configuration file ✅

- Created `config.yaml` with all user-editable settings
- `config.py` loads YAML, casts types, derives computed values

### 2.3 Hardcoded rotation ✅

- Made `rotation_angle` configurable in `config.yaml`
- Set to `0` after discovering map image is geographic north-up

### 2.4 Error handling ✅

- Added `_validate_coords()` with 1° bounds check
- Consolidated 3 duplicate bearing functions into `_bearing_deg()` using `math.pi`
- Replaced all `print()` with `logging.debug()`/`info()`

---

## Phase 3: Logic Fixes ✅ (completed)

### 3.1 Bounding box replaced ✅

- Entirely replaced bounding-box approach with `MapProjection` anchor-point system
- Similarity transform from 2+ GPS→pixel anchor pairs
- Works for any screen size — just update anchor pixel positions

### 3.2 GPS data integration ✅

- Replaced all hardcoded test coordinates with official 2026 GIS data
- 19 landmarks from `cpns.geojson` and `trash_fence.geojson`
- The Man, Temple, Center Camp, all G-street and B-street plazas, pentagon vertices

### 3.3 Duplicate bearing functions ✅

- Consolidated into single `_bearing_deg()` using `math.pi`

---

## Phase 4: Calibration Tool ✅ (completed — not in original plan)

### calibrate.py — web-based calibration ✅

- HTTP server at `localhost:8050`
- Simulates full e-ink screen (480×800) with map, pentagon, test points
- Click to set anchor pixel positions in screen coordinates
- Live projection computation in JavaScript
- Download config.yaml with updated anchors
- 19 landmarks selectable as anchors

### MapProjection (`projection.py`) ✅

- Similarity transform from 2+ anchor points
- `gps_to_pixel()` and `pixel_to_gps()` methods
- `dump()` for diagnostic output

### Makefile ✅

- `make test` — venv, install, run in debug+screen mode
- `make calibrate` — launch calibration web server
- Laptop-safe `requirements-dev.txt` (no RPi.GPIO/spidev)

---

## Phase 5: Code Quality & Split Display Map

### 5.1 Split display_map.py into modules

- **Current**: `display_map.py` handles Meshtastic polling, coordinate conversion, rendering, hardware in one ~400-line file.
- **Target**:
  - `mesh.py` — Meshtastic connection, polling, node data extraction
  - `renderer.py` — PIL drawing logic (dots, pentagon, labels, lines)
  - `display_map.py` — main loop orchestrator only

### 5.2 Dead code removal

- Clean up unused imports (`fontawesome`, `cairosvg`, etc.)
- Remove `burning_man_to_gps()` if unused
- Remove legacy config values no longer needed

### 5.3 Unit tests

- `projection.py` — anchor computation, GPS↔pixel round-trip
- `coordinates.py` — BRC address formatting, bearing math
- Framework: pytest

### 5.4 Logging improvements

- Structured logging for node position data
- Configurable log levels

---

## Phase 6: Feature Additions

### 6.1 Battery and signal indicators

- Show battery level, RSSI/SNR from Meshtastic telemetry

### 6.2 Stale node handling

- Grey out / remove nodes not heard from in N minutes

### 6.3 Position history

- Log positions to SQLite, render last N positions as trail

### 6.4 Web dashboard

- Lightweight HTTP status page for phone access on-playa

---

## Phase 7: Hardware & Deployment

### 7.1 systemd service

### 7.2 Health check / watchdog

### 7.3 Power optimization

---

## Phase 8: Documentation

### 8.1 Hardware setup guide

### 8.2 Configuration guide

### 8.3 Troubleshooting
