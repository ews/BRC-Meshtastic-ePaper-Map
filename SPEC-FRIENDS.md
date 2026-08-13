# Friend Filtering System — Specification

## Overview

Currently `display_map.py` shows *every* Meshtastic node on the mesh network.
This spec defines a **friend-based filtering system** that limits the ePaper
display to only show positions of specific, whitelisted nodes ("friends").

A companion web interface lets the user add, remove, and edit friends without
editing files.

---

## 1. Data Model

### 1.1 Friend record

Each friend is stored with the following fields:

| Field | Type | Required | Description |
| ------- | ------ | ---------- | ------------- |
| `node_id` | string (hex) | ✅ | Meshtastic node ID (e.g. `!abcd1234`) — stable unique identifier |
| `name` | string | ✅ | Display name for the ePaper (e.g. `"Alice"`) |
| `short_name` | string | | Abbreviated label (e.g. `"AL"`) — falls back to first 2 chars of name |
| `emoji` | string | ✅ | Persistent e-paper-safe symbol selected in the searchable picker |
| `notes` | string | | Free-text notes (camp name, vehicle, etc.) |
| `color` | string | | Tag color hint for future use (e.g. `"red"`, `"blue"`) |
| `added_at` | ISO-8601 | auto | When the friend was added |

### 1.2 Node ID as primary key

The Meshtastic `node_id` (a `!` prefix + 8 hex chars) is the **stable unique
identifier**. It does not change when the user renames their device. The
`name` field is a human-readable label that the user sets.

Matching incoming mesh nodes to friends is done by `node_id`, not by name.

### 1.3 Storage format

A JSON file: `friends.json` in the project root.

```json
{
  "version": 1,
  "friends": [
    {
      "node_id": "!abcd1234",
      "name": "Alice",
      "short_name": "AL",
      "emoji": "♥",
      "notes": "Camp Quark @ 7:30 & C",
      "added_at": "2026-08-20T12:00:00Z"
    }
  ]
}
```

**Why JSON rather than SQLite:**

- Zero dependencies (JSON is built into Python)
- Human-readable and editable in a text editor as a fallback
- Easy to version-control
- Sufficient for the expected scale (10–50 friends, not 10,000)

If performance becomes an issue later, migration to SQLite is straightforward.

---

## 2. Filtering Logic

### 2.1 Integration point

The filter sits between `mesh.get_mesh_info()` and `renderer.draw_node_labels()`
in `display_map.py`:

```
mesh.get_mesh_info()
    ↓
add_bm_coordinates()        # convert GPS to BRC addresses
    ↓
[new] filter_friends()      # keep only whitelisted node_ids
    ↓
draw_node_labels()          # render to ePaper
```

### 2.2 filter_friends() function

```python
def filter_friends(burners, friends):
    """Return only burners whose node_id is in the friends list."""
    friend_ids = {f["node_id"] for f in friends}
    return {
        name: data
        for name, data in burners.items()
        if data.get("node_id") in friend_ids
    }
```

### 2.3 Friend-list writes

`friends.json` is only written when a friend is added, edited, removed, or
migrated. Position and chat history belongs in `mesh_history.sqlite3`.

### 2.4 Edge cases

| Case | Behavior |
| ------ | ---------- |
| Empty friends list | Show nothing (not "show everyone") — explicit opt-in |
| Node appears with matching ID but different name | Use stored `name` for display |
| Friend's node hasn't been heard from in N hours | Show last known position with "(stale)" indicator or greyed out |
| Duplicate node_ids in friends.json | Last one wins; validation rejects duplicates on save |

---

## 3. Web Management Interface

### 3.1 Architecture

A lightweight HTTP server runs **in a background thread** within the main
display process. This avoids needing a separate deployment.

```
┌─ main process ───────────────────────────────┐
│                                               │
│  while True:                                  │
│      poll mesh → filter → render → sleep      │
│                                               │
│  ┌─ background thread ────────────────────┐   │
│  │  HTTP server (port 8051)               │   │
│  │  POST /api/friends  (add)              │   │
│  │  DELETE /api/friends/<node_id>         │   │
│  │  PUT /api/friends/<node_id> (edit)     │   │
│  │  GET /api/friends  (list)              │   │
│  │  GET /api/nodes    (live mesh nodes)   │   │
│  │  GET /             (management UI)     │   │
│  └────────────────────────────────────────┘   │
└───────────────────────────────────────────────┘
```

**Port choice:** 8051 (calibrator uses 8050, display uses 8051).

### 3.2 REST API

#### `GET /api/friends`

Returns the full friends list as JSON.

```
[{"node_id": "!abcd1234", "name": "Alice", ...}, ...]
```

#### `POST /api/friends`

Add a new friend. Body:

```json
{"node_id": "!abcd1234", "name": "Alice", "notes": "Camp Quark", "emoji": "♥"}
```

Returns `201` with the created record. Returns `409` if node_id already exists.

#### `PUT /api/friends/<node_id>`

Edit an existing friend. Body can include any subset of fields:

```json
{"name": "Alice (updated)", "notes": "Moved to 9:00 & D", "emoji": "★"}
```

Returns `200` with updated record. Returns `404` if not found.

#### `DELETE /api/friends/<node_id>`

Remove a friend. Returns `204`. Returns `404` if not found.

#### `GET /api/nodes`

Returns all mesh nodes currently visible (for the "add friend" picker).

```
[{"node_id": "!abcd1234", "name": "Alice", "last_heard": 1234567890, "is_friend": true}, ...]
```

### 3.3 Web UI pages

#### Main page (`GET /`)

A simple single-page app with two panels:

**Left panel — My Friends (current list)**

| Column | Description |
| -------- | ------------- |
| Name | Editable text field |
| Node ID | Read-only, with copy button |
| Short name | Editable text field (max 4 chars) |
| Notes | Editable text field |
| Last seen | Auto-updated timestamp |
| Actions | Edit (pencil icon), Delete (trash icon) |

**Right panel — Discover (live mesh nodes)**

Shows all nodes currently on the mesh that are NOT already friends.
Each row has an **"Add"** button.

**Top bar:**

- Title: "BRC Friend Manager"
- Status indicator: "● Connected — 5 friends, 12 nodes on mesh"
- Refresh button (re-polls /api/nodes)

#### Styling

- Dark theme matching the calibrator (`#1a1a2e` background, `#e94560` accents)
- Monospace font
- Mobile-friendly (will be used on a phone on-playa)
- No external CSS/JS dependencies (single HTML file, same pattern as calibrator)

### 3.4 Implementation approach

Single Python file `friend_server.py` containing:

- `FriendStore` class — reads/writes `friends.json` with thread-safe locking
- HTTP handler using `http.server` (same as calibrator — no Flask dependency)
- Embedded HTML/CSS/JS (single-page app)

---

## 4. File Layout

```
BRC-Meshtastic-ePaper-Map/
├── friends.json           ← friend database (created on first run)
├── friend_server.py       ← HTTP server + FriendStore
├── history_store.py       ← SQLite position and chat history
├── display_map.py         ← updated to call filter_friends()
├── calibrate.py           ← unchanged
├── config.yaml            ← add friends_file and friend_server_port
...
```

### 4.1 Config additions (`config.yaml`)

```yaml
# Friend filtering
friends_file: "friends.json"
friend_server_port: 8051
history_database: "mesh_history.sqlite3"
```

---

## 5. Thread Safety

The `friends.json` file is read by the main display loop (every ~60 seconds)
and written by the web API only on user action. To prevent corruption:

1. `FriendStore` uses a `threading.Lock` for all read/write operations
2. The display loop calls `friend_store.get_friends()` to get a snapshot
3. The web handlers call `friend_store.add_friend()` etc.
4. File I/O is atomic: write to a temp file, then `os.replace()` (POSIX atomic rename)

---

## 6. Startup Sequence

Updated `main()` in `display_map.py`:

```
1. Load config
2. Load map image
3. Load friends from friends.json
4. Start friend_server in background thread (if enabled in config)
5. Connect to Meshtastic
6. Main loop:
   a. Poll mesh nodes
   b. Convert GPS coordinates
   c. Save all node positions to SQLite
   d. Filter to friends only for display
   e. If displayed positions changed, render to ePaper
   f. Save incoming text messages to SQLite via the receive callback
   g. Sleep
7. Shutdown: stop friend_server thread, close mesh interface
```

---

## 7. Future Extensions (not in scope)

- **Groups** — tag friends into groups (e.g. "camp", "art car") to show/hide
- **Color coding** — assign the E6 panel's native colors to friends
- **Geofencing** — alert when a friend enters/exits a defined area
- **Push notifications** — webhook/Telegram when a friend moves
- **SQLite backend** — migrate from JSON if friend count exceeds ~100
- **Mesh node discovery history** — keep a log of all node IDs ever seen

---

## 8. Acceptance Criteria

- [ ] Adding a friend via the web UI immediately filters the ePaper display (next poll cycle)
- [ ] Removing a friend hides their position on next poll
- [ ] Editing a friend's name updates the ePaper label
- [ ] Unknown mesh nodes do NOT appear on the ePaper
- [ ] `friends.json` is valid JSON at all times (no corruption on concurrent access)
- [ ] Web UI works on a phone browser (responsive, touch-friendly)
- [ ] Friend server starts/stops cleanly with the main process
- [ ] If `friends.json` is empty, ePaper shows "No friends configured" message
