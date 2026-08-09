#!/usr/bin/env python3
"""Friend management web server — runs in a background thread.

Provides a REST API and single-page web UI for managing the friend list.
Access at http://<host>:8051 when running.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from friend_store import FriendStore

ROOT = Path(__file__).resolve().parent

# ── Embedded single-page web UI ────────────────────────────────
UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BRC Friend Manager</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:monospace;background:#1a1a2e;color:#eee;display:flex;flex-direction:column;min-height:100vh}
header{background:#16213e;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #0f3460}
header h1{color:#e94560;font-size:16px}
#status{font-size:11px;color:#4ecca3}
main{display:flex;flex:1;overflow:hidden}
.panel{flex:1;padding:16px;overflow-y:auto}
.panel h2{color:#f5c518;font-size:13px;margin-bottom:10px}
#left{border-right:2px solid #0f3460}
table{width:100%;border-collapse:collapse;font-size:11px}
th{text-align:left;color:#888;padding:6px 4px;border-bottom:1px solid #333;font-size:10px;position:sticky;top:0;background:#1a1a2e}
td{padding:5px 4px;border-bottom:1px solid #222;vertical-align:top}
td input{background:#0f3460;border:1px solid #444;color:#eee;padding:3px 5px;font-family:monospace;font-size:11px;width:100%;border-radius:3px}
td input:focus{border-color:#e94560;outline:none}
.node-id{color:#888;font-size:10px}
button{background:#e94560;color:#fff;border:none;padding:4px 10px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:10px}
button:hover{background:#ff6b81}
button.dim{background:#0f3460}
button.dim:hover{background:#1a5276}
button.green{background:#4ecca3;color:#000}
button.green:hover{background:#6eecc3}
.add-form{margin-bottom:16px;display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap}
.add-form input{background:#0f3460;border:1px solid #444;color:#eee;padding:5px 8px;font-family:monospace;font-size:11px;border-radius:3px}
.add-form input:focus{border-color:#e94560;outline:none}
.add-form label{font-size:10px;color:#aaa}
.empty{color:#666;font-size:12px;padding:20px;text-align:center}
.last-seen{font-size:9px;color:#666}
</style>
</head>
<body>
<header>
  <h1>👥 BRC Friend Manager</h1>
  <div id="status">● Loading...</div>
</header>
<main>
  <div class="panel" id="left">
    <h2>My Friends</h2>

    <div class="add-form">
      <div>
        <label>Node ID</label>
        <input id="add-id" placeholder="!abcd1234" style="width:130px">
      </div>
      <div>
        <label>Name</label>
        <input id="add-name" placeholder="Alice" style="width:110px">
      </div>
      <div>
        <label>Notes</label>
        <input id="add-notes" placeholder="Camp @ 7:30 & C" style="width:160px">
      </div>
      <button onclick="addFriend()">Add</button>
    </div>

    <div id="friends-list"></div>
  </div>

  <div class="panel" id="right">
    <h2>Mesh Nodes (live)</h2>
    <button onclick="refreshNodes()" class="dim" style="margin-bottom:8px">↻ Refresh</button>
    <div id="nodes-list"></div>
  </div>
</main>

<script>
const BASE = '';

function status(msg) { document.getElementById('status').textContent = msg; }

async function api(method, path, body) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(BASE + path, opts);
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`${r.status} ${err}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

// ── Friends list ──────────────────────────────────────────────
async function loadFriends() {
  try {
    const friends = await api('GET', '/api/friends');
    renderFriends(friends);
    status(`● ${friends.length} friends loaded`);
  } catch(e) {
    status('⚠ ' + e.message);
  }
}

function renderFriends(friends) {
  const el = document.getElementById('friends-list');
  if (!friends.length) {
    el.innerHTML = '<div class="empty">No friends yet. Add one above or pick from Mesh Nodes →</div>';
    return;
  }
  let html = '<table><tr><th>Name</th><th>Short</th><th>Node ID</th><th>Notes</th><th>Last Seen</th><th></th></tr>';
  friends.forEach(f => {
    html += `<tr>
      <td><input value="${esc(f.name)}" onchange="updateFriend('${f.node_id}','name',this.value)"></td>
      <td><input value="${esc(f.short_name||'')}" onchange="updateFriend('${f.node_id}','short_name',this.value)" style="width:50px" maxlength="4"></td>
      <td><span class="node-id">${esc(f.node_id)}</span></td>
      <td><input value="${esc(f.notes||'')}" onchange="updateFriend('${f.node_id}','notes',this.value)"></td>
      <td class="last-seen">${f.last_seen ? f.last_seen.slice(11,16)+' '+f.last_seen.slice(5,10) : 'never'}</td>
      <td><button onclick="removeFriend('${f.node_id}')" class="dim">✕</button></td>
    </tr>`;
  });
  html += '</table>';
  el.innerHTML = html;
}

async function addFriend() {
  const nid = document.getElementById('add-id').value.trim();
  const name = document.getElementById('add-name').value.trim();
  const notes = document.getElementById('add-notes').value.trim();
  if (!nid || !name) { status('⚠ Need Node ID and Name'); return; }
  try {
    await api('POST', '/api/friends', {node_id:nid, name, notes});
    document.getElementById('add-id').value = '';
    document.getElementById('add-name').value = '';
    document.getElementById('add-notes').value = '';
    loadFriends();
    refreshNodes();
  } catch(e) { status('⚠ ' + e.message); }
}

async function updateFriend(nid, field, value) {
  try {
    const body = {}; body[field] = value;
    await api('PUT', '/api/friends/' + encodeURIComponent(nid), body);
    status('✓ Updated');
  } catch(e) { status('⚠ ' + e.message); }
}

async function removeFriend(nid) {
  if (!confirm('Remove ' + nid + '?')) return;
  try {
    await api('DELETE', '/api/friends/' + encodeURIComponent(nid));
    loadFriends();
    refreshNodes();
    status('✓ Removed');
  } catch(e) { status('⚠ ' + e.message); }
}

// ── Mesh nodes ────────────────────────────────────────────────
async function refreshNodes() {
  try {
    const nodes = await api('GET', '/api/nodes');
    renderNodes(nodes);
    status(`● ${nodes.length} nodes on mesh`);
  } catch(e) {
    document.getElementById('nodes-list').innerHTML = '<div class="empty">⚠ Cannot reach mesh — is display_map.py running?</div>';
  }
}

function renderNodes(nodes) {
  const el = document.getElementById('nodes-list');
  if (!nodes.length) {
    el.innerHTML = '<div class="empty">No mesh nodes detected.</div>';
    return;
  }
  let html = '<table><tr><th>Name</th><th>Node ID</th><th></th></tr>';
  nodes.forEach(n => {
    const action = n.is_friend
      ? '<span style="color:#4ecca3;font-size:10px">✓ friend</span>'
      : `<button onclick="quickAdd('${esc(n.node_id)}','${esc(n.name||'')}')" class="green">+ Add</button>`;
    html += `<tr>
      <td>${esc(n.name||'unknown')}</td>
      <td><span class="node-id">${esc(n.node_id)}</span></td>
      <td>${action}</td>
    </tr>`;
  });
  html += '</table>';
  el.innerHTML = html;
}

function quickAdd(nid, name) {
  document.getElementById('add-id').value = nid;
  document.getElementById('add-name').value = name || '';
  document.getElementById('add-name').focus();
}

function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Init ──────────────────────────────────────────────────────
loadFriends();
refreshNodes();
setInterval(refreshNodes, 30000);
</script>
</body>
</html>"""


class FriendServer(threading.Thread):
    """Background thread running the friend management HTTP server."""

    def __init__(self, store: FriendStore, mesh_interface=None, port: int = 8051):
        super().__init__(daemon=True, name="friend-server")
        self._store = store
        self._mesh = mesh_interface  # set later by display_map
        self._port = port

    def set_mesh(self, interface):
        """Attach a Meshtastic interface for live node discovery."""
        self._mesh = interface

    def run(self):
        server = HTTPServer(
            ("0.0.0.0", self._port), _make_handler(self._store, self._mesh)
        )
        print(f"[friend-server] listening on :{self._port}")
        server.serve_forever()

    def get_port(self) -> int:
        return self._port


def _make_handler(store, mesh_iface):
    """Factory to bind store and mesh to the handler class."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._serve_html(UI_HTML)
            elif path == "/api/friends":
                self._serve_json(store.get_friends())
            elif path == "/api/nodes":
                self._serve_json(_list_mesh_nodes(mesh_iface, store))
            elif path.startswith("/api/friends/"):
                node_id = path.split("/api/friends/")[1]
                friend = store.get_by_id(node_id)
                if friend:
                    self._serve_json(friend)
                else:
                    self._error(404, "not found")
            else:
                self._error(404, "not found")

        def do_POST(self):
            path = urlparse(self.path).path
            body = self._read_body()
            if path == "/api/friends":
                try:
                    record = store.add(
                        node_id=body.get("node_id", ""),
                        name=body.get("name", ""),
                        notes=body.get("notes", ""),
                    )
                    self._serve_json(record, status=201)
                except ValueError as e:
                    self._error(409, str(e))

        def do_PUT(self):
            path = urlparse(self.path).path
            body = self._read_body()
            if path.startswith("/api/friends/"):
                node_id = path.split("/api/friends/")[1]
                try:
                    record = store.update(node_id, **body)
                    self._serve_json(record)
                except KeyError:
                    self._error(404, "not found")

        def do_DELETE(self):
            path = urlparse(self.path).path
            if path.startswith("/api/friends/"):
                node_id = path.split("/api/friends/")[1]
                try:
                    store.remove(node_id)
                    self._respond(204)
                except KeyError:
                    self._error(404, "not found")

        def _read_body(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                return {}
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}

        def _serve_json(self, data, status=200):
            body = json.dumps(data, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_html(self, html):
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code, msg):
            body = json.dumps({"error": msg}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _respond(self, code):
            self.send_response(code)
            self.end_headers()

        def log_message(self, format, *args):
            pass  # quiet

    return Handler


def _list_mesh_nodes(mesh_iface, store: FriendStore) -> list[dict]:
    """Return all mesh nodes with an is_friend flag."""
    if mesh_iface is None:
        return []
    friend_ids = store.get_friend_ids()
    nodes = []
    try:
        for node_id, data in mesh_iface.nodes.items():
            user = data.get("user", {})
            nodes.append(
                {
                    "node_id": node_id,
                    "name": user.get("longName", user.get("shortName", "")),
                    "is_friend": node_id in friend_ids,
                }
            )
    except Exception:
        pass
    return nodes
