# Improvement Plan

## Phase 1: Bug Fixes ✅ (completed)

All known runtime bugs fixed and committed.

| # | Bug | File | Severity | Status |
| --- | --- | --- | --- | --- |
| 1 | `MAN_LAT = 40.783242,` — trailing comma makes it a tuple, silently breaking all geopy distance calculations | `config.py` | Critical | ✅ Fixed |
| 2 | `new[burgner]` typo → `NameError` at runtime | `display_map.py` | Critical | ✅ Fixed |
| 3 | `distance_ft()` called with latitude twice instead of `(lat, lon)` for new point | `display_map.py` | High | ✅ Fixed |
| 4 | `[(c.man_svg[0], 0), (c.man_svg[0]), c.HEIGHT-10]` — malformed tuple, syntax error | `display_map.py` | Critical | ✅ Fixed |
| 5 | README references `draw_map.py` but filename is `display_map.py` | `README.org` | Low | ✅ Fixed |
| 6 | `burners_log.write(burner)` writes dict key, not structured data; global fd never flushed/closed | `config.py` + `display_map.py` | High | ✅ Fixed |
| 7 | `equal_bm_coordinates` misses node join/leave — only checks movement of known nodes | `display_map.py` | Medium | ✅ Fixed |
| 8 | Red drawing layer never cleared each iteration → label/dot accumulation (ghosting) | `display_map.py` | Medium | ✅ Fixed |
| 9 | `interface.close()` dead code after infinite `while True`; no `KeyboardInterrupt` handling | `display_map.py` | Medium | ✅ Fixed |

---

## Phase 2: Architecture & Robustness

### 2.1 Connection resilience

- **Problem**: If the serial/TCP Meshtastic connection drops, the script crashes. No reconnect logic.
- **Fix**: Wrap `get_mesh_info(interface)` in a retry loop with exponential backoff. On disconnect, attempt reconnection before failing.

### 2.2 Configuration file

- **Problem**: All configuration is in `config.py` as executable Python code. Users must edit code to set coordinates.
- **Fix**: Extract user-configurable values (coordinates, display options, street distances, BRC noon angle) into a `config.yaml` or `config.toml` file. Load it at startup. Keep derived values in `config.py`.

### 2.3 Hardcoded 45° rotation

- **Problem**: BRC's city grid orientation shifts slightly year-to-year. The 45° rotation is hardcoded in `gps_to_image_coordinates` and `gps_to_burning_man`.
- **Fix**: Make `rotation_angle` and `city_angle` top-level config parameters.

### 2.4 Error handling in coordinate conversion

- **Problem**: `gps_to_burning_man` and `gps_to_image_coordinates` have no input validation. Invalid GPS values could produce nonsensical screen coordinates.
- **Fix**: Add bounds checking. Return `None` or raise a clear error for coordinates outside BRC's plausible area.

---

## Phase 3: Logic Fixes

### 3.1 Bounding box is wrong for a rotated pentagon

- **Problem**: `gps_to_image_coordinates` derives its bounding box from `lat_min`/`lat_max`/`lon_min`/`lon_max` which are calculated assuming the city is a perfect circle aligned N/S/E/W. BRC is a pentagon rotated 45°, so the AABB is incorrect.
- **Fix**: Calculate the true bounding box of the pentagon (or at least use a tighter bounding box based on the actual city footprint).

### 3.2 Street name lookup edge case

- **Problem**: When a node is between two streets (e.g., between Esplanade and A), the current `for/else` logic assigns it to the first street whose distance exceeds the remaining distance. This means the node is assigned to the *outer* street, not the nearest one.
- **Fix**: After finding the matching street, check whether the remaining distance to that street or the distance past it is smaller, and pick the closer street.

### 3.3 Duplicate bearing functions

- **Problem**: `get_bearing_ang`, `get_bearing_rad`, and `calculate_initial_compass_bearing` in `coordinates.py` are near-duplicates.
- **Fix**: Consolidate into a single `bearing()` function. Use `math.pi` instead of hardcoded approximations (`3.14159`, `3.1415`).

---

## Phase 4: Feature Additions

### 4.1 Battery and signal indicators

- **Data available**: Meshtastic node dict includes `batteryLevel`, `voltage`, `snr`, `rssi`.
- **Implementation**: Show small battery icon or signal bars next to each node label. Grey out nodes with critically low battery.

### 4.2 Stale node handling

- **Problem**: Nodes that go offline stay on the map indefinitely.
- **Implementation**: Track `lastSeen` timestamp per node. Grey out or remove nodes not heard from in N minutes (configurable).

### 4.3 Position history / trails

- **Implementation**: Log positions to a SQLite database. Optionally render the last N positions as a faint trail behind each node. Could replay movement over time.

### 4.4 Configurable POI database

- **Problem**: Only Temple and The Man are known landmarks (`known_camps` dict in `gps_to_burning_man`).
- **Implementation**: Load named points of interest from a JSON/YAML file. Display camp names when a node is within `camp_radius` feet.

### 4.5 Web dashboard

- **Implementation**: Run a lightweight HTTP server (Flask or aiohttp) on the Raspberry Pi. Serve a real-time HTML page with current node positions, last seen times, signal strength. Would be accessible via phone while on-playa without needing the ePaper screen.

### 4.6 Text message display

- **Data available**: Meshtastic supports text messaging between nodes.
- **Implementation**: Display the last received text message from each node in a scrolling ticker at the bottom of the ePaper screen.

### 4.7 Multiple map layers

- **Implementation**: Support switching between day/night map images, or between different year layouts. Could auto-switch based on time of day.

### 4.8 Automatic timezone / BRC noon adjustment

- **Problem**: `BRC_NOON` is hardcoded to `1.5` (1.5 hours offset). Burning Man's official clock is Pacific Time, but the city grid's angular offset may change.
- **Implementation**: Make BRC noon a configurable float. Optionally auto-detect from GPS location + timezone.

---

## Phase 5: Code Quality & Testing

### 5.1 Unit tests

- **Priority targets**:
  - `gps_to_burning_man()` — known inputs → expected outputs
  - `gps_to_image_coordinates()` — GPS → pixel coordinate correctness
  - `burning_man_to_gps()` — round-trip conversion
  - `distance_ft()` — known lat/lon pairs → expected distances
  - `equal_bm_coordinates()` — movement threshold logic
- **Framework**: pytest

### 5.2 Separation of concerns

- **Current**: `display_map.py` handles Meshtastic polling, coordinate conversion, rendering, and ePaper hardware in one 300-line file.
- **Target**:
  - `mesh.py` — Meshtastic connection, polling, node data extraction
  - `renderer.py` — PIL drawing logic (dots, pentagon, labels, lines)
  - `display.py` — ePaper hardware driver (or screen output)
  - `display_map.py` — main loop orchestrator only

### 5.3 Dead code removal

- `burning_man_to_gps()` — imported in `display_map.py` but never called
- `get_bearing_ang()` and `get_bearing_rad()` — never called externally (only used internally? verify)
- `fontawesome` import — removed from requirements if not needed (it was imported but never used)
- `cairosvg`, `CairoSVG`, `pillow-svg` — the SVG rendering path appears unused (map is loaded as PNG)

### 5.4 Logging improvements

- **Problem**: `print()` is used alongside `logging` for debug output.
- **Fix**: Replace all `print()` calls with `logging.debug()` or `logging.info()`. Use structured logging for node position data.

### 5.5 Type hints

- Add type annotations to all public functions for better IDE support and catching bugs early.

---

## Phase 6: Hardware & Deployment

### 6.1 systemd service

- Create a `.service` file so the script starts on boot and restarts on crash.
- Example: `/etc/systemd/system/brc-meshtastic-map.service`

### 6.2 Health check

- Add a watchdog timer — if no nodes have been heard from in N minutes, display a warning on the ePaper ("No mesh activity").
- Optionally blink an LED or trigger a buzzer for critical failures.

### 6.3 Power optimization

- ePaper only needs power during refresh. Consider deeper sleep between poll cycles on battery power.
- Profile power usage on a Raspberry Pi Zero vs Pi 4.

---

## Phase 7: Documentation

### 7.1 Hardware setup guide

- Step-by-step photos/instructions for connecting the WaveShare ePaper HAT to a Raspberry Pi.
- Wiring diagram for SPI connection.
- Enclosure/case recommendations for desert conditions (dust, heat).

### 7.2 User configuration guide

- How to edit `config.yaml` (after Phase 2.2).
- How to find GPS coordinates for a new location.
- How to calibrate the map (finding pixel coordinates for The Man on a new map image).

### 7.3 Troubleshooting

- Common errors and solutions (serial port permissions, SPI not enabled, Meshtastic device not found).
- How to use `--debug` mode to verify coordinate mapping.
