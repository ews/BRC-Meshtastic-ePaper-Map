#!/usr/bin/env python3
"""Channel 1 node and emoji management web server.

Provides a REST API and responsive UI for assigning symbols to found nodes.
Access at http://<host>:8051 when running.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from burner_emojis import default_emoji
from friend_store import FriendStore

ROOT = Path(__file__).resolve().parent
PICKER_ROOT = ROOT / "vendor" / "emoji-picker-element"
WEB_ASSETS = {
    "/assets/emoji-picker-element/index.js": (
        PICKER_ROOT / "index.js",
        "text/javascript",
    ),
    "/assets/emoji-picker-element/picker.js": (
        PICKER_ROOT / "picker.js",
        "text/javascript",
    ),
    "/assets/emoji-picker-element/database.js": (
        PICKER_ROOT / "database.js",
        "text/javascript",
    ),
    "/assets/emoji-picker-element/emoji-data.json": (
        PICKER_ROOT / "emoji-data.json",
        "application/json",
    ),
}

# ── Embedded single-page web UI ────────────────────────────────
UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111827">
<title>Channel 1 Locations</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--card:#151d31;--card2:#1b2740;--line:#2b3a58;--text:#f4f7fb;--muted:#94a3b8;--accent:#f43f5e;--green:#34d399;--blue:#60a5fa}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(circle at top,#17233d 0,var(--bg) 46%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input{font:inherit}
button{touch-action:manipulation}
header{position:sticky;top:0;z-index:3;padding:max(18px,env(safe-area-inset-top)) 18px 14px;background:#0b1020e8;border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}
.header-row{max-width:820px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:14px}
.title-wrap{display:flex;align-items:center;gap:12px;min-width:0}
.logo{display:grid;place-items:center;width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#fb7185,#be123c);font-size:23px;box-shadow:0 8px 28px #be123c44}
h1{margin:0;font-size:20px;line-height:1.15;letter-spacing:-.02em}
.subtitle{margin-top:3px;color:var(--muted);font-size:12px}
.channel-badge{flex:none;padding:7px 10px;border:1px solid #34d39955;border-radius:999px;background:#064e3b55;color:#86efac;font-size:12px;font-weight:700}
main{width:min(820px,100%);margin:auto;padding:18px 18px calc(30px + env(safe-area-inset-bottom))}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:15px}
#status{color:var(--muted);font-size:13px}
.refresh{min-height:42px;padding:0 15px;border:1px solid var(--line);border-radius:12px;background:var(--card2);color:var(--text);font-weight:700;cursor:pointer}
.refresh:hover,.refresh:focus-visible{border-color:var(--blue);outline:none}
.nodes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.node-card{display:grid;grid-template-columns:64px minmax(0,1fr);gap:13px;align-items:center;padding:15px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,var(--card2),var(--card));box-shadow:0 10px 30px #0003}
.emoji-button{width:64px;height:64px;border:1px solid #475569;border-radius:18px;background:#0f172a;color:var(--text);font-size:31px;cursor:pointer;box-shadow:inset 0 0 0 1px #ffffff08}
.emoji-button:hover,.emoji-button:focus-visible{border-color:var(--green);outline:3px solid #34d39922;transform:translateY(-1px)}
.node-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:800;font-size:16px}
.node-id{margin-top:3px;color:var(--muted);font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.location{margin-top:8px;color:#bfdbfe;font-size:13px;line-height:1.35}
.seen{margin-top:3px;color:var(--muted);font-size:11px}
.custom{display:inline-block;margin-left:6px;padding:2px 6px;border-radius:999px;background:#064e3b;color:#a7f3d0;font-size:9px;vertical-align:2px}
.empty{grid-column:1/-1;padding:48px 24px;border:1px dashed #334155;border-radius:18px;text-align:center;color:var(--muted);line-height:1.55}
.empty strong{display:block;margin-bottom:6px;color:var(--text);font-size:17px}
.modal{position:fixed;inset:0;z-index:10;display:grid;place-items:center;padding:18px;background:#020617c7;backdrop-filter:blur(5px)}
.modal.hidden{display:none}
.picker{width:min(520px,100%);max-height:min(650px,90vh);overflow:hidden;border:1px solid #475569;border-radius:22px;background:#111827;box-shadow:0 28px 80px #000a}
.picker-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 18px 10px}
.picker-title{min-width:0}
.picker-title strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:17px}
.picker-title span{color:var(--muted);font-size:12px}
.close{width:44px;height:44px;flex:none;border:1px solid var(--line);border-radius:50%;background:var(--card2);color:var(--text);font-size:20px;cursor:pointer}
.emoji-picker-host{display:grid;place-items:center;padding:8px 18px 20px}
emoji-picker{width:100%;height:min(470px,65vh);--background:#111827;--border-color:#334155;--border-radius:14px;--input-border-color:#64748b;--input-font-color:#f4f7fb;--input-placeholder-color:#94a3b8;--indicator-color:#34d399;--outline-color:#60a5fa;--category-font-color:#e2e8f0;--button-active-background:#334155;--button-hover-background:#263654;--emoji-size:1.55rem;--emoji-padding:.48rem}
.toast{position:fixed;left:50%;bottom:calc(20px + env(safe-area-inset-bottom));z-index:20;transform:translateX(-50%);max-width:calc(100% - 36px);padding:11px 15px;border-radius:12px;background:#ecfdf5;color:#064e3b;font-weight:700;font-size:13px;box-shadow:0 12px 40px #0007}
.toast.error{background:#fff1f2;color:#9f1239}
.toast.hidden{display:none}
@media(max-width:680px){
  header{padding-left:14px;padding-right:14px}.logo{width:40px;height:40px;border-radius:12px}h1{font-size:18px}.channel-badge{padding:6px 8px}
  main{padding-left:12px;padding-right:12px}.nodes{grid-template-columns:1fr}.node-card{padding:13px}.emoji-button{width:58px;height:58px;border-radius:16px}
  .modal{align-items:end;padding:0}.picker{width:100%;max-height:92vh;border-radius:24px 24px 0 0;padding-bottom:env(safe-area-inset-bottom)}.emoji-picker-host{padding-left:12px;padding-right:12px}emoji-picker{height:min(520px,72vh);--emoji-size:1.65rem;--emoji-padding:.42rem}
}
@media(max-width:370px){.subtitle{display:none}.channel-badge{font-size:10px}emoji-picker{--emoji-size:1.5rem;--emoji-padding:.35rem}}
</style>
</head>
<body>
<header>
  <div class="header-row">
    <div class="title-wrap">
      <div class="logo">⌖</div>
      <div><h1>Camp Locations</h1><div class="subtitle">Tap an icon to personalize it</div></div>
    </div>
    <div class="channel-badge">● Channel 1</div>
  </div>
</header>
<main>
  <div class="toolbar"><div id="status" aria-live="polite">Listening for locations…</div><button class="refresh" onclick="refreshNodes()">↻ Refresh</button></div>
  <div id="nodes-list" class="nodes"><div class="empty"><strong>Waiting for Channel 1</strong>Nodes appear after their next shared location arrives.</div></div>
</main>
<div id="emoji-modal" class="modal hidden" onclick="modalBackground(event)" role="dialog" aria-modal="true" aria-labelledby="picker-name">
  <div class="picker">
    <div class="picker-head">
      <div class="picker-title"><strong id="picker-name">Choose an icon</strong><span id="picker-id"></span></div>
      <button class="close" onclick="closeEmojiPicker()" aria-label="Close">×</button>
    </div>
    <div class="emoji-picker-host">
      <emoji-picker class="dark" data-source="/assets/emoji-picker-element/emoji-data.json"></emoji-picker>
    </div>
  </div>
</div>
<div id="toast" class="toast hidden" role="status"></div>
<script>
let nodes = [];
let pickerNode = null;
let toastTimer = null;

async function api(method, path, body) {
  const options = {method, headers:{'Content-Type':'application/json'}};
  if (body) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = await response.text();
    try { message = JSON.parse(message).error || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

async function refreshNodes() {
  const status = document.getElementById('status');
  status.textContent = 'Refreshing…';
  try {
    nodes = await api('GET', '/api/nodes');
    renderNodes();
    status.textContent = nodes.length === 1 ? '1 location found' : `${nodes.length} locations found`;
  } catch (error) {
    status.textContent = 'Unable to load locations';
    showToast(error.message, true);
  }
}

function renderNodes() {
  const list = document.getElementById('nodes-list');
  if (!nodes.length) {
    list.innerHTML = '<div class="empty"><strong>Waiting for Channel 1</strong>Nodes appear after their next shared location arrives.</div>';
    return;
  }
  list.innerHTML = nodes.map((node, index) => `
    <article class="node-card">
      <button class="emoji-button" onclick="openEmojiPicker(${index})" aria-label="Choose icon for ${esc(node.name)}">${esc(node.emoji)}</button>
      <div class="node-info">
        <div class="node-name">${esc(node.name)}${node.custom_emoji?'<span class="custom">CUSTOM</span>':''}</div>
        <div class="node-id">${esc(node.node_id)}</div>
        <div class="location">${esc(node.brc_address||'Location received')}</div>
        <div class="seen">${formatTime(node.position_time)}</div>
      </div>
    </article>`).join('');
}

function openEmojiPicker(index) {
  pickerNode = nodes[index];
  document.getElementById('picker-name').textContent = pickerNode.name;
  document.getElementById('picker-id').textContent = pickerNode.node_id;
  document.getElementById('emoji-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeEmojiPicker() {
  document.getElementById('emoji-modal').classList.add('hidden');
  document.body.style.overflow = '';
  pickerNode = null;
}

function modalBackground(event) {
  if (event.target.id === 'emoji-modal') closeEmojiPicker();
}

async function chooseEmoji(symbol) {
  if (!pickerNode) return;
  const nodeId = pickerNode.node_id;
  try {
    await api('PUT', `/api/nodes/${encodeURIComponent(nodeId)}/emoji`, {emoji:symbol});
    closeEmojiPicker();
    await refreshNodes();
    showToast('Icon saved');
  } catch (error) {
    showToast(error.message, true);
  }
}

function formatTime(timestamp) {
  if (!timestamp) return 'Position time unavailable';
  const value = new Date(Number(timestamp) * 1000);
  return `Shared ${value.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
}

function showToast(message, error=false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast${error?' error':''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), 3000);
}

function esc(value) {
  return String(value||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

document.addEventListener('keydown', event => { if (event.key === 'Escape') closeEmojiPicker(); });
refreshNodes();
setInterval(refreshNodes, 15000);
</script>
<script type="module">
import '/assets/emoji-picker-element/index.js';
document.querySelector('emoji-picker').addEventListener('emoji-click', event => {
  chooseEmoji(event.detail.unicode);
});
</script>
</body>
</html>"""


class FriendServer(threading.Thread):
    """Background thread running the Channel 1 emoji web app."""

    def __init__(self, store: FriendStore, node_source=None, port: int = 8051):
        super().__init__(daemon=True, name="channel-location-server")
        self._store = store
        self._node_source = node_source or (lambda: [])
        self._port = port

    def run(self):
        server = HTTPServer(
            ("0.0.0.0", self._port),
            _make_handler(self._store, self._node_source),
        )
        print(f"[channel-location-server] listening on :{self._port}")
        server.serve_forever()

    def get_port(self) -> int:
        return self._port


def _make_handler(store, node_source):
    """Factory binding preference storage and the live Channel 1 node source."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._serve_html(UI_HTML)
            elif path in WEB_ASSETS:
                self._serve_asset(*WEB_ASSETS[path])
            elif path == "/api/friends":
                self._serve_json(store.get_friends())
            elif path == "/api/nodes":
                self._serve_json(_list_channel_nodes(node_source, store))
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
                        emoji=body.get("emoji") or None,
                    )
                    self._serve_json(record, status=201)
                except ValueError as e:
                    self._error(409, str(e))

        def do_PUT(self):
            path = urlparse(self.path).path
            body = self._read_body()
            if path.startswith("/api/nodes/") and path.endswith("/emoji"):
                node_id = path.removeprefix("/api/nodes/").removesuffix("/emoji")
                try:
                    record = _set_node_emoji(
                        store, node_source, node_id, body.get("emoji", "")
                    )
                    self._serve_json(record)
                except KeyError:
                    self._error(404, "channel 1 node not found")
                except ValueError as e:
                    self._error(409, str(e))
            elif path.startswith("/api/friends/"):
                node_id = path.split("/api/friends/")[1]
                try:
                    record = store.update(node_id, **body)
                    self._serve_json(record)
                except KeyError:
                    self._error(404, "not found")
                except ValueError as e:
                    self._error(409, str(e))

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

        def _serve_asset(self, asset_path, content_type):
            try:
                body = asset_path.read_bytes()
            except OSError:
                self._error(404, "asset not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=86400")
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


def _list_channel_nodes(node_source, store: FriendStore) -> list[dict]:
    """Return found Channel 1 nodes with their effective symbols."""
    preferences = {
        record["node_id"]: record for record in store.get_friends()
    }
    source_nodes = [dict(node) for node in node_source()]
    visible_ids = {node["node_id"] for node in source_nodes}
    used = {
        record["emoji"]
        for node_id, record in preferences.items()
        if node_id in visible_ids
    }
    nodes = []
    for result in sorted(source_nodes, key=lambda item: item["node_id"]):
        preference = preferences.get(result["node_id"])
        if preference:
            result["emoji"] = preference["emoji"]
            result["custom_emoji"] = True
        else:
            result["emoji"] = default_emoji(result["node_id"], used)
            result["custom_emoji"] = False
            used.add(result["emoji"])
        nodes.append(result)
    return sorted(nodes, key=lambda item: item.get("name", "").lower())


def _set_node_emoji(store, node_source, node_id, emoji):
    """Create or update a persistent emoji preference for a found node."""
    node = next(
        (item for item in node_source() if item.get("node_id") == node_id),
        None,
    )
    if node is None:
        raise KeyError(node_id)
    existing = store.get_by_id(node_id)
    if existing:
        return store.update(node_id, emoji=emoji)
    return store.add(node_id=node_id, name=node.get("name", node_id), emoji=emoji)
