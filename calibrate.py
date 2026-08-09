#!/usr/bin/env python3
"""Calibration web app — click on the map image to set anchor pixel positions.

Usage:
    python3 calibrate.py
    # Open http://localhost:8050 in a browser
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CONFIG_PATH = ROOT / "config.yaml"

# ── embedded HTML ──────────────────────────────────────────────
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BRC Map Calibrator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: monospace; background: #1a1a2e; color: #eee; display: flex; height: 100vh; }
  #sidebar { width: 380px; padding: 16px; overflow-y: auto; background: #16213e; border-right: 2px solid #0f3460; }
  #sidebar h2 { margin-bottom: 12px; color: #e94560; }
  #sidebar p { margin-bottom: 8px; font-size: 12px; color: #aaa; }
  #main { flex: 1; display: flex; align-items: center; justify-content: center; position: relative; overflow: auto; }
  canvas { cursor: crosshair; image-rendering: pixelated; }
  .section { margin-bottom: 16px; }
  .section h3 { color: #f5c518; margin-bottom: 6px; font-size: 13px; }
  .anchor-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }
  .anchor-row span { width: 80px; }
  .anchor-row input { width: 60px; background: #0f3460; border: 1px solid #333; color: #eee; padding: 2px 6px; font-family: monospace; border-radius: 3px; }
  .anchor-row input:focus { border-color: #e94560; outline: none; }
  .anchor-row .gps { color: #888; font-size: 10px; }
  button { background: #e94560; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 12px; margin: 4px 2px; }
  button:hover { background: #ff6b81; }
  button.secondary { background: #0f3460; }
  button.secondary:hover { background: #1a5276; }
  #status { font-size: 11px; color: #4ecca3; margin-top: 8px; min-height: 16px; }
  #info { font-size: 11px; color: #aaa; margin-top: 4px; }
  #anchor-list { margin-top: 8px; }
  .active { color: #e94560; font-weight: bold; }
  .crosshair { position: absolute; pointer-events: none; }
</style>
</head>
<body>
<div id="sidebar">
  <h2>🎯 BRC Map Calibrator</h2>
  <p>Click on the map to set anchor positions. Click on different anchors below to select which one you're placing.</p>

  <div class="section">
    <h3>1. Select anchor to place:</h3>
    <div id="anchor-list"></div>
  </div>

  <div class="section">
    <h3>2. Controls:</h3>
    <button onclick="clearAll()">Clear All</button>
    <button onclick="useDefaults()" class="secondary">Reset Defaults</button>
    <button onclick="downloadConfig()" style="background:#4ecca3;color:#000;">📥 Download config.yaml</button>
  </div>

  <div class="section">
    <h3>3. Projection:</h3>
    <div id="proj-info" style="font-size:11px;"></div>
  </div>

  <div class="section">
    <h3>4. Verify — test points:</h3>
    <div id="test-points" style="font-size:11px;"></div>
  </div>

  <div id="status">Click on the map to place the selected anchor →</div>
  <div id="info">Map: LOADING... | Zoom: 100%</div>
</div>
<div id="main">
  <canvas id="map"></canvas>
</div>

<script>
// ── Data from server ──────────────────────────────────────────
const MAP_URL = "/map.png";
const ANCHORS = __ANCHORS__;
const TEST_POINTS = __TEST_POINTS__;
const SCREEN_W = __SCREEN_W__;
const SCREEN_H = __SCREEN_H__;
const IMAGE_X = __IMAGE_X__;
const IMAGE_Y = __IMAGE_Y__;
const FEET_PER_DEG = __FEET_PER_DEG__;

// ── State ─────────────────────────────────────────────────────
let selectedIdx = 0;
let pixelCoords = ANCHORS.map(a => ({ x: a[2], y: a[3], set: a[2] > 0 || a[3] > 0 }));
let mapImg = null;
let zoom = 1.0;

// ── DOM ───────────────────────────────────────────────────────
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
const infoEl = document.getElementById('info');
const anchorList = document.getElementById('anchor-list');
const projInfo = document.getElementById('proj-info');
const testDiv = document.getElementById('test-points');

// ── Build anchor list UI ──────────────────────────────────────
function buildAnchorUI() {
  let html = '';
  ANCHORS.forEach((a, i) => {
    const name = a[4] || `anchor-${i}`;
    const set = pixelCoords[i].set;
    html += `<div class="anchor-row ${i === selectedIdx ? 'active' : ''}" onclick="selectAnchor(${i})" style="cursor:pointer;">
      <span>${i === selectedIdx ? '▶' : '&nbsp;'} ${name}</span>
      <span class="gps">(${a[0].toFixed(4)},${a[1].toFixed(4)})</span>
      <input type="number" id="px-${i}" value="${set ? pixelCoords[i].x : ''}" placeholder="x" style="width:50px"
        onclick="event.stopPropagation()" onchange="updatePixel(${i},'x',this.value)" />
      <input type="number" id="py-${i}" value="${set ? pixelCoords[i].y : ''}" placeholder="y" style="width:50px"
        onclick="event.stopPropagation()" onchange="updatePixel(${i},'y',this.value)" />
      ${set ? '✓' : '⚠'}
    </div>`;
  });
  anchorList.innerHTML = html;
}

function selectAnchor(i) {
  selectedIdx = i;
  buildAnchorUI();
  statusEl.textContent = `Click on map to place "${ANCHORS[i][4]}" →`;
  drawAll();
}

function updatePixel(i, axis, val) {
  const v = parseInt(val) || 0;
  if (axis === 'x') pixelCoords[i].x = v;
  else pixelCoords[i].y = v;
  pixelCoords[i].set = true;
  drawAll();
  updateProjection();
}

// ── Map loading ───────────────────────────────────────────────
function loadMap() {
  mapImg = new Image();
  mapImg.onload = () => {
    canvas.width = mapImg.width;
    canvas.height = mapImg.height;
    infoEl.textContent = `Map: ${mapImg.width}×${mapImg.height} | Screen: ${SCREEN_W}×${SCREEN_H} | Image pos: (${IMAGE_X},${IMAGE_Y})`;
    drawAll();
  };
  mapImg.src = MAP_URL;
}

// ── Drawing ───────────────────────────────────────────────────
function drawAll() {
  if (!mapImg) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(mapImg, 0, 0);

  // Draw anchor markers
  ANCHORS.forEach((a, i) => {
    const px = pixelCoords[i];
    if (!px.set) return;
    const sx = px.x - IMAGE_X;
    const sy = px.y - IMAGE_Y;
    const isSelected = i === selectedIdx;

    // Crosshair
    ctx.strokeStyle = isSelected ? '#e94560' : '#4ecca3';
    ctx.lineWidth = isSelected ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(sx - 15, sy); ctx.lineTo(sx + 15, sy);
    ctx.moveTo(sx, sy - 15); ctx.lineTo(sx, sy + 15);
    ctx.stroke();

    // Circle
    ctx.beginPath();
    ctx.arc(sx, sy, isSelected ? 8 : 5, 0, Math.PI * 2);
    ctx.stroke();

    // Label
    ctx.fillStyle = isSelected ? '#e94560' : '#4ecca3';
    ctx.font = '12px monospace';
    ctx.fillText(a[4] || `#${i}`, sx + 10, sy - 8);
  });

  // Draw test points if we have a valid projection
  drawTestPoints();
}

function projectGPS(lat, lon) {
  // Simple client-side projection matching projection.py logic
  // Requires at least 2 set anchors
  const setAnchors = ANCHORS.filter((_, i) => pixelCoords[i].set);
  if (setAnchors.length < 2) return null;

  const a0 = setAnchors[0];
  const a1 = setAnchors[1];
  const i0 = ANCHORS.indexOf(a0);
  const i1 = ANCHORS.indexOf(a1);

  const lat0 = a0[0], lon0 = a0[1], px0 = pixelCoords[i0].x, py0 = pixelCoords[i0].y;
  const lat1 = a1[0], lon1 = a1[1], px1 = pixelCoords[i1].x, py1 = pixelCoords[i1].y;

  const cosLat = Math.cos(lat0 * Math.PI / 180);
  const dx_ft = (lon1 - lon0) * FEET_PER_DEG * cosLat;
  const dy_ft = (lat1 - lat0) * FEET_PER_DEG;
  const dx_px = px1 - px0;
  const dy_px = py1 - py0;

  const dist_ft = Math.hypot(dx_ft, dy_ft);
  const dist_px = Math.hypot(dx_px, dy_px);
  if (dist_ft < 1 || dist_px < 1) return null;

  const scale = dist_px / dist_ft;
  const angle_geo = Math.atan2(dy_ft, dx_ft);
  const angle_px = Math.atan2(-dy_px, dx_px);
  const rot = angle_px - angle_geo;

  const c = scale * Math.cos(rot);
  const s = scale * Math.sin(rot);

  const dx_f = (lon - lon0) * FEET_PER_DEG * cosLat;
  const dy_f = (lat - lat0) * FEET_PER_DEG;

  return {
    x: px0 + c * dx_f - s * dy_f,
    y: py0 - s * dx_f - c * dy_f,
    scale, rot_deg: rot * 180 / Math.PI
  };
}

function drawTestPoints() {
  const r = projectGPS(0, 0);
  if (!r) return;

  TEST_POINTS.forEach(tp => {
    const p = projectGPS(tp[0], tp[1]);
    if (!p) return;
    const sx = p.x - IMAGE_X;
    const sy = p.y - IMAGE_Y;
    if (sx < 0 || sy < 0 || sx > canvas.width || sy > canvas.height) return;

    ctx.fillStyle = '#f5c518';
    ctx.font = '10px monospace';
    ctx.fillText(tp[2], sx + 4, sy - 4);
    ctx.beginPath();
    ctx.arc(sx, sy, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function updateProjection() {
  const r = projectGPS(0, 0);
  if (!r) {
    projInfo.innerHTML = 'Need 2+ anchors set';
    testDiv.innerHTML = '';
    return;
  }
  projInfo.innerHTML = `Scale: ${(1/r.scale).toFixed(1)} ft/px &nbsp;|&nbsp; Rotation: ${r.rot_deg.toFixed(2)}°`;

  let thtml = '';
  TEST_POINTS.forEach(tp => {
    const p = projectGPS(tp[0], tp[1]);
    if (!p) return;
    const onScreen = (p.x >= 0 && p.x <= SCREEN_W && p.y >= 0 && p.y <= SCREEN_H);
    thtml += `<div style="font-size:10px; color:${onScreen ? '#4ecca3' : '#e94560'}">
      ${tp[2]}: screen (${Math.round(p.x)},${Math.round(p.y)}) ${onScreen ? '' : 'OFF'}</div>`;
  });
  testDiv.innerHTML = thtml;
  drawAll();
}

// ── Canvas click ──────────────────────────────────────────────
canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = Math.round(e.clientX - rect.left);
  const sy = Math.round(e.clientY - rect.top);

  pixelCoords[selectedIdx].x = sx + IMAGE_X;
  pixelCoords[selectedIdx].y = sy + IMAGE_Y;
  pixelCoords[selectedIdx].set = true;

  document.getElementById(`px-${selectedIdx}`).value = pixelCoords[selectedIdx].x;
  document.getElementById(`py-${selectedIdx}`).value = pixelCoords[selectedIdx].y;

  buildAnchorUI();
  drawAll();
  updateProjection();
  statusEl.textContent = `✓ ${ANCHORS[selectedIdx][4]} set at screen (${pixelCoords[selectedIdx].x}, ${pixelCoords[selectedIdx].y})`;
});

// ── Actions ───────────────────────────────────────────────────
function clearAll() {
  pixelCoords.forEach(p => { p.x = 0; p.y = 0; p.set = false; });
  buildAnchorUI();
  drawAll();
  updateProjection();
  statusEl.textContent = 'Cleared — click map to place anchors';
}

function useDefaults() {
  ANCHORS.forEach((a, i) => {
    pixelCoords[i].x = a[2];
    pixelCoords[i].y = a[3];
    pixelCoords[i].set = true;
    const xi = document.getElementById(`px-${i}`);
    const yi = document.getElementById(`py-${i}`);
    if (xi) xi.value = a[2];
    if (yi) yi.value = a[3];
  });
  buildAnchorUI();
  drawAll();
  updateProjection();
  statusEl.textContent = 'Reset to default anchor positions';
}

function downloadConfig() {
  const lines = [];
  lines.push('# Generated by calibrate.py');
  lines.push('anchors:');
  ANCHORS.forEach((a, i) => {
    const px = pixelCoords[i];
    lines.push(`  - [${a[0]}, ${a[1]}, ${px.set ? px.x : a[2]}, ${px.set ? px.y : a[3]}]  # ${a[4] || 'anchor-'+i}`);
  });

  const blob = new Blob([lines.join('\n')], {type: 'text/yaml'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'anchors.yaml';
  a.click();
  statusEl.textContent = 'Downloaded anchors.yaml — merge into config.yaml';
}

// ── Init ──────────────────────────────────────────────────────
buildAnchorUI();
loadMap();
updateProjection();
</script>
</body>
</html>"""


def build_page():
    """Inject Python data into the HTML template."""
    import yaml

    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_PATH} not found — run from project root")
        sys.exit(1)

    anchors = cfg["anchors"]
    # Add names for anchors
    anchor_names = ["The Man", "The Temple", "Center Camp", "9:00 & G", "3:00 & G"]
    named_anchors = []
    for i, a in enumerate(anchors):
        name = anchor_names[i] if i < len(anchor_names) else f"anchor-{i}"
        named_anchors.append(a + [name])

    test_points = [
        [40.783247, -119.207884, "man"],
        [40.788099, -119.201500, "temple"],
        [40.777372, -119.215612, "center"],
        [40.792611, -119.220207, "9G"],
        [40.783245, -119.225308, "730G"],
        [40.770004, -119.207883, "430G"],
        [40.773883, -119.195565, "3G"],
    ]

    return (
        PAGE.replace("__ANCHORS__", json.dumps(named_anchors))
        .replace("__TEST_POINTS__", json.dumps(test_points))
        .replace("__SCREEN_W__", str(cfg["display"]["width"]))
        .replace("__SCREEN_H__", str(cfg["display"]["height"]))
        .replace("__IMAGE_X__", str(cfg["image_position"][0]))
        .replace("__IMAGE_Y__", str(cfg["image_position"][1]))
        .replace("__FEET_PER_DEG__", str(cfg["feet_per_degree"]))
    )


def serve_map_png():
    """Read the map PNG as bytes."""
    map_path = ROOT / "media" / "Map_1bit.png"
    try:
        with open(map_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        print(f"ERROR: {map_path} not found")
        sys.exit(1)


def main():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    page_html = build_page().encode()
    map_png = serve_map_png()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page_html)
            elif self.path == "/map.png":
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(map_png)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            print(f"[calibrate] {args[0]}")

    port = 8050
    print("🔧 BRC Map Calibrator")
    print(f"   Open http://localhost:{port} in your browser")
    print("   Click the map to set anchor positions")
    print("   Press Ctrl+C to stop")
    print()

    server = HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
