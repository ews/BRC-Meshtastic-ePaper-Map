# BRC Meshtastic ePaper Map

Real-time GPS tracking and visualization for Burning Man using Meshtastic
mesh networks and a WaveShare ePaper display.

![screenshot](media/display_map.png)

---

## Table of Contents

1. [Overview](#overview)
2. [Files & Architecture](#files--architecture)
3. [Quick Start (laptop test)](#quick-start-laptop-test)
4. [Configuration](#configuration)
5. [Map Calibration](#map-calibration)
6. [Friend Filtering System](#friend-filtering-system)
7. [Raspberry Pi Deployment](#raspberry-pi-deployment)
8. [Development](#development)
9. [Data Sources](#data-sources)

---

## Overview

Connects to a Meshtastic LoRa radio (serial or TCP), polls for node GPS
positions, converts them to Burning Man clock+street addresses, and renders
them on a WaveShare 7.3" E6/Spectra 6 full-color PhotoPainter display
(800×480).

### Key features

- **GPS → BRC address** conversion (e.g. `"07:30 + Esplanade"`)
- **Anchor-point map projection** — calibrate once with 2+ GPS→pixel pairs
- **Web calibration tool** (`calibrate.py`) — click to set anchor positions
- **Friend filtering** — only show whitelisted node IDs on the display
- **Web management UI** (`friend_server.py`) — add/remove/edit friends
- **Exponential backoff retry** on mesh connection drops
- **Debug mode** with test coordinates and calibration overlays

---

## Files & Architecture

```
BRC-Meshtastic-ePaper-Map/
├── display_map.py        # Main loop: poll → filter → render → sleep
├── config.yaml           # User configuration (anchors, screen size, etc.)
├── config.py             # Loads config.yaml + builds MapProjection
│
├── projection.py         # GPS→pixel similarity transform (anchor-based)
├── coordinates.py        # GPS→BRC address, GPS→pixel wrappers
│
├── mesh.py               # Meshtastic connection, polling, node extraction
├── renderer.py           # PIL drawing: dots, pentagon, labels, test coords
├── friend_store.py       # Thread-safe JSON friend database
├── friend_server.py      # REST API + web UI for friend management (port 8051)
│
├── calibrate.py          # Web calibration tool (port 8050)
├── Makefile              # npm-style: make install, make test, make calibrate
├── pyproject.toml        # Package metadata, deps, tool config (package.json equivalent)
│
├── tests/
│   └── test_projection.py # 9 unit tests for MapProjection
│
├── media/
│   ├── Map_1bit.png      # BRC city map (1-bit, 465×371)
│   └── Font.ttc          # Font for labels
│
├── requirements.txt      # Pi dependencies (tight pins)
├── requirements-dev.txt  # Laptop dependencies (relaxed pins)
│
├── PLAN.md               # Improvement plan & status
├── SPEC-FRIENDS.md        # Friend filtering spec
└── README.md             # This file
```

### Data flow

```
Meshtastic Radio
    │
    ▼
mesh.py: connect_serial() → get_mesh_info() → add_bm_coordinates()
    │                                              │
    │                                    coordinates.py: gps_to_burning_man()
    │                                    coordinates.py: gps_to_image_coordinates()
    │                                              │
    ▼                                              ▼
display_map.py: filter friends by node_id (friend_store.py)
    │
    ▼
renderer.py: draw_node_labels() → ePaper display
```

### Projection math

```python
# projection.py — similarity transform from 2+ anchor points
proj = MapProjection([
    (man_lat,  man_lon,  man_px_x,  man_px_y),
    (temple_lat, temple_lon, temple_px_x, temple_px_y),
])
x, y = proj.gps_to_pixel(lat, lon)
```

The transform automatically computes scale, rotation, and translation from
the anchor pairs. No hardcoded bounding boxes, angles, or radii.

---

## Quick Start (laptop test)

No ePaper or Meshtastic radio needed. Works like `npm install`:

```bash
cd BRC-Meshtastic-ePaper-Map
make install   # creates .venv, installs package in editable mode
make test      # runs display in --debug --screen mode
```

A window opens showing the BRC map with test point labels. See all targets:

```bash
make help
```

---

## Configuration

All user settings are in `config.yaml`:

### Screen & display

```yaml
display:
  width: 480
  height: 800

image_position: [6, 400]     # where Map_1bit.png is pasted on screen
sleep_seconds: 60             # mesh poll interval
```

### Map calibration (the critical part)

```yaml
anchors:
  - [40.783247, -119.207884, 240, 516]   # The Man: lat, lon, screen_x, screen_y
  - [40.788099, -119.201500, 311, 444]   # The Temple

feet_per_degree: 364000
```

Only 2 anchors are needed to define the projection. Use `make calibrate` to
set pixel positions by clicking on the map.

### BRC geometry (for address display only)

```yaml
brc:
  man_lat: 40.783247
  man_long: -119.207884
  distance_man_esplanade: 2500
  distance_streets: [400, 250, 250, 250, 250, 250, 450, 250, 250, 250, 150, 150]
  brc_noon: 1.5
```

### Friend filtering

```yaml
friends_file: "friends.json"
friend_server_port: 8051
```

---

## Map Calibration

The web calibration tool simulates the e-ink screen:

```bash
make calibrate
# Open http://localhost:8050
```

### Steps

1. Select an anchor in the sidebar (e.g. "The Man")
2. Click on the map image where that landmark appears
3. Repeat for "The Temple" or another known point
4. Check the yellow test point dots — they should land on correct map features
5. Click **Download config.yaml** and paste the anchors into `config.yaml`

The projection updates in real-time as you click. The pentagon is drawn from
GIS trash fence vertices projected through your calibration.

---

## Friend Filtering System

### Overview

By default, the ePaper shows **only whitelisted friends** (not all mesh nodes).
An empty friends list shows nothing — explicit opt-in.

### Web management UI

```bash
# Starts automatically with display_map.py
# Open http://<pi-ip>:8051
```

Two panels:

- **Left — My Friends**: List with inline name/short-name/notes editing,
  add form, delete buttons
- **Right — Mesh Nodes**: Live mesh nodes with **"+ Add"** buttons to
  quickly whitelist a node

### REST API

| Method | Path | Description |
| -------- | ------ | ------------- |
| `GET` | `/api/friends` | List all friends |
| `POST` | `/api/friends` | Add a friend `{"node_id":"!abcd","name":"Alice"}` |
| `PUT` | `/api/friends/<id>` | Edit fields `{"name":"New name"}` |
| `DELETE` | `/api/friends/<id>` | Remove a friend |
| `GET` | `/api/nodes` | Live mesh nodes with `is_friend` flag |

### Storage

`friends.json` — thread-safe JSON with atomic writes. Each friend record:

```json
{
  "node_id": "!abcd1234",
  "name": "Alice",
  "short_name": "AL",
  "notes": "Camp Quark @ 7:30 & C",
  "added_at": "2026-08-20T12:00:00Z",
  "last_seen": "2026-08-20T14:30:00Z"
}
```

### Bypass filtering

```bash
python3 display_map.py --no-friends   # shows all mesh nodes
```

---

## Raspberry Pi Deployment

### Hardware

- Raspberry Pi (Zero 2W, 3, or 4)
- WaveShare 7.3" E6 full-color PhotoPainter for Raspberry Pi Zero (800×480)
- Meshtastic radio (serial or TCP)

This PhotoPainter uses the `epd7in3e` driver and its board-specific BCM 27
power pin. Older `epd7in5_V2` monochrome/tri-color drivers are incompatible.

### Install

```bash
git clone <repo>
cd BRC-Meshtastic-ePaper-Map
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Enable SPI

```bash
sudo raspi-config
# Interface Options → SPI → Enable
```

### Run

```bash
make run-map
```

The base map is displayed immediately, before Meshtastic connection retries.
The friend management server starts automatically at port 8051.
Access it from your phone at `http://<pi-ip>:8051`.

### CLI flags

| Flag | Description |
| ------ | ------------- |
| `-d`, `--debug` | Use test coordinates instead of Meshtastic |
| `-s`, `--screen` | Show on desktop window instead of ePaper |
| `-c`, `--calibrate` | Print GPS→pixel conversion details |
| `--no-friends` | Show all mesh nodes (disable friend filtering) |

---

## Development

### Makefile reference

```bash
make install       # create venv + pip install -e .[dev]  (like npm install)
make install-pi    # same but with RPi.GPIO + spidev for Raspberry Pi
make test          # run display in --debug --screen mode
make calibrate     # launch calibration tool → http://localhost:8050
make pytest        # run unit tests
make clean         # remove venv, caches, build artifacts
make help          # show all targets
```

### Project packaging

`pyproject.toml` is the Python equivalent of `package.json`. It defines:

- Project name, version, description
- Dependencies with relaxed version pins
- `[dev]` extras: pytest
- `[pi]` extras: RPi.GPIO, spidev
- Ruff formatter and pytest config

The `-e` flag in `pip install -e .` installs in **editable mode** — changes
to `.py` files take effect immediately, no reinstall needed.

### Running tests

```bash
make pytest       # or: .venv/bin/pytest tests/ -v
```

9 tests covering MapProjection: identity, scale, rotation (north-up,
east-right), round-trip accuracy, anchor reproduction, input validation,
and diagnostic output.

### Code style

Auto-formatted with ruff. Pre-existing warnings about geopy imports
(not installed in dev env) and ast-grep "unchecked-throwing-call" rules
are expected in this environment.

### Key design decisions

- **JSON over SQLite for friends** — simpler, human-readable, zero-dependency.
  Migration to SQLite is straightforward if needed (sqlite3 is in stdlib).
- **Background thread for web server** — avoids separate deployment. Uses
  `http.server` from stdlib (no Flask dependency).
- **Anchor-point projection** — replaced bounding-box math after discovering
  the map image is geographic north-up, not BRC-grid-up.
- **Similarity transform** — scale, rotation, and translation from 2+ anchors.
  Works for any screen size.

---

## Data Sources

All GPS coordinates sourced from the official 2026 Burning Man GIS data:

- `innovate-GIS-data/2026/GeoJSON/cpns.geojson` — The Man, Temple, Center Camp,
  and 40+ named points
- `innovate-GIS-data/2026/GeoJSON/plazas.geojson` — G and B street plaza
  centroids
- `innovate-GIS-data/2026/GeoJSON/trash_fence.geojson` — pentagon vertices
- `innovate-GIS-data/2026/GeoJSON/street_lines.geojson` — street centerlines

19 landmarks are embedded in `calibrate.py` and `renderer.py` as test points.
