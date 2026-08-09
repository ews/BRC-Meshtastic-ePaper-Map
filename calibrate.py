#!/usr/bin/env python3
"""Calibration web app — simulates the e-ink screen with live GPS-to-pixel projection.

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

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BRC ePaper Map Calibrator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: monospace; background: #1a1a2e; color: #eee; display: flex; height: 100vh; }
  #sidebar { width: 380px; padding: 16px; overflow-y: auto; background: #16213e; border-right: 2px solid #0f3460; }
  #sidebar h2 { margin-bottom: 4px; color: #e94560; font-size: 15px; }
  #sidebar .subtitle { font-size: 11px; color: #aaa; margin-bottom: 12px; }
  #main { flex: 1; display: flex; align-items: center; justify-content: center; background: #111; overflow: auto; }
  canvas { cursor: crosshair; border: 1px solid #333; }
  .section { margin-bottom: 14px; }
  .section h3 { color: #f5c518; margin-bottom: 4px; font-size: 12px; }
  .anchor-row { display: flex; align-items: center; gap: 6px; margin: 3px 0; font-size: 11px; padding: 2px 4px; border-radius: 3px; }
  .anchor-row:hover { background: #0f3460; }
  .anchor-row span.name { width: 80px; cursor: pointer; }
  .anchor-row span.gps { color: #888; font-size: 9px; width: 140px; }
  .anchor-row input { width: 52px; background: #0f3460; border: 1px solid #444; color: #eee; padding: 2px 4px; font-family: monospace; font-size: 11px; border-radius: 3px; }
  .anchor-row input:focus { border-color: #e94560; outline: none; }
  button { background: #e94560; color: #fff; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 11px; margin: 2px 2px; }
  button:hover { background: #ff6b81; }
  button.green { background: #4ecca3; color: #000; }
  button.green:hover { background: #6eecc3; }
  button.dim { background: #0f3460; }
  button.dim:hover { background: #1a5276; }
  #status { font-size: 11px; color: #4ecca3; margin-top: 8px; min-height: 16px; }
  #info { font-size: 10px; color: #888; margin-top: 4px; }
  .active { background: #0f3460; border-radius: 3px; }
  .set-badge { color: #4ecca3; font-size: 10px; }
  .unset-badge { color: #e94560; font-size: 10px; }
  select, input[type=number] { background: #0f3460; border: 1px solid #444; color: #eee; padding: 3px 6px; font-family: monospace; font-size: 11px; border-radius: 3px; }
</style>
</head>
<body>
<div id="sidebar">
  <h2>🗺️ BRC ePaper Calibrator</h2>
  <div class="subtitle">Simulates the exact e-ink screen layout</div>

  <div class="section">
    <h3>Screen</h3>
    <label>Resolution: </label>
    <input type="number" id="scrn-w" value="__SCREEN_W__" style="width:55px" onchange="resizeScreen()"> ×
    <input type="number" id="scrn-h" value="__SCREEN_H__" style="width:55px" onchange="resizeScreen()">
    <label style="margin-left:8px;">Map pos:</label>
    <input type="number" id="img-x" value="__IMAGE_X__" style="width:50px" onchange="resizeScreen()">,
    <input type="number" id="img-y" value="__IMAGE_Y__" style="width:50px" onchange="resizeScreen()">
  </div>

  <div class="section">
    <h3>Anchors (click to select, then click map)</h3>
    <div id="anchor-list"></div>
    <button onclick="clearAll()" class="dim">Clear All</button>
    <button onclick="useDefaults()" class="dim">Reset Defaults</button>
  </div>

  <div class="section">
    <h3>Projection</h3>
    <div id="proj-info" style="font-size:10px;color:#f5c518;"></div>
  </div>

  <div class="section">
    <h3>Test points on screen:</h3>
    <div id="test-points" style="font-size:10px;"></div>
  </div>

  <button onclick="downloadConfig()" class="green" style="width:100%;">📥 Download config.yaml</button>
  <div id="status" style="margin-top:10px;">Click a landmark on the map →</div>
  <div id="info">Map: __MAP_W__×__MAP_H__</div>
</div>
<div id="main">
  <canvas id="screen"></canvas>
</div>

<script>
const MAP_URL = "/map.png";
const ANCHORS = __ANCHORS__;
const TEST_POINTS = __TEST_POINTS__;
const PENT_POINTS = __PENT_POINTS__;
const TRASH_FENCE_FT = __TRASH_FENCE_FT__;
const FEET_PER_DEG = __FEET_PER_DEG__;
const DEFAULT_SCREEN_W = __SCREEN_W__;
const DEFAULT_SCREEN_H = __SCREEN_H__;

// State
let selectedIdx = 0;
let pixelCoords = ANCHORS.map(a => ({ x: a[2], y: a[3], set: true }));
let mapImg = null;
let screenW = DEFAULT_SCREEN_W;
let screenH = DEFAULT_SCREEN_H;
let imgX = __IMAGE_X__;
let imgY = __IMAGE_Y__;

const canvas = document.getElementById('screen');
const ctx = canvas.getContext('2d');

function resizeScreen() {
  screenW = parseInt(document.getElementById('scrn-w').value) || 480;
  screenH = parseInt(document.getElementById('scrn-h').value) || 800;
  imgX = parseInt(document.getElementById('img-x').value) || 6;
  imgY = parseInt(document.getElementById('img-y').value) || 400;
  canvas.width = screenW;
  canvas.height = screenH;
  drawAll();
  updateProjection();
}

// ── Anchors UI ────────────────────────────────────────────────
function buildAnchorUI() {
  let html = '';
  ANCHORS.forEach((a, i) => {
    const name = a[4] || `#${i}`;
    const set = pixelCoords[i].set;
    html += `<div class="anchor-row${i === selectedIdx ? ' active' : ''}" onclick="selectAnchor(${i})" style="cursor:pointer;">
      <span class="name">${i === selectedIdx ? '▶' : ''} ${name}</span>
      <span class="gps">${a[0].toFixed(5)},${a[1].toFixed(5)}</span>
      <input id="px-${i}" value="${set ? pixelCoords[i].x : ''}" placeholder="x"
        onclick="event.stopPropagation()" onchange="updatePixel(${i},'x',this.value)" />
      <input id="py-${i}" value="${set ? pixelCoords[i].y : ''}" placeholder="y"
        onclick="event.stopPropagation()" onchange="updatePixel(${i},'y',this.value)" />
      <span class="${set ? 'set-badge' : 'unset-badge'}">${set ? '✓' : '?'}</span>
    </div>`;
  });
  document.getElementById('anchor-list').innerHTML = html;
}

function selectAnchor(i) { selectedIdx = i; buildAnchorUI(); drawAll(); }

function updatePixel(i, axis, val) {
  const v = parseInt(val) || 0;
  if (axis === 'x') pixelCoords[i].x = v; else pixelCoords[i].y = v;
  pixelCoords[i].set = true;
  document.getElementById(`px-${i}`).value = pixelCoords[i].x;
  document.getElementById(`py-${i}`).value = pixelCoords[i].y;
  drawAll(); updateProjection();
}

// ── Projection math (matches projection.py) ────────────────────
function projectGPS(lat, lon) {
  const setAnchors = ANCHORS.filter((_, i) => pixelCoords[i].set);
  if (setAnchors.length < 2) return null;
  const a0 = setAnchors[0], a1 = setAnchors[1];
  const i0 = ANCHORS.indexOf(a0), i1 = ANCHORS.indexOf(a1);

  const lat0 = a0[0], lon0 = a0[1];
  const px0 = pixelCoords[i0].x, py0 = pixelCoords[i0].y;
  const px1 = pixelCoords[i1].x, py1 = pixelCoords[i1].y;

  const cosLat = Math.cos(lat0 * Math.PI / 180);
  const dx_ft = (a1[1] - lon0) * FEET_PER_DEG * cosLat;
  const dy_ft = (a1[0] - lat0) * FEET_PER_DEG;
  const dx_px = px1 - px0, dy_px = py1 - py0;

  const dist_ft = Math.hypot(dx_ft, dy_ft);
  const dist_px = Math.hypot(dx_px, dy_px);
  if (dist_ft < 1 || dist_px < 1) return null;

  const scale = dist_px / dist_ft;
  const rot = Math.atan2(-dy_px, dx_px) - Math.atan2(dy_ft, dx_ft);
  const c = scale * Math.cos(rot), s = scale * Math.sin(rot);

  const dxf = (lon - lon0) * FEET_PER_DEG * cosLat;
  const dyf = (lat - lat0) * FEET_PER_DEG;

  return {
    x: px0 + c * dxf - s * dyf,
    y: py0 - s * dxf - c * dyf,
    scale, rot_deg: rot * 180 / Math.PI
  };
}

// ── Drawing ───────────────────────────────────────────────────
function drawAll() {
  canvas.width = screenW;
  canvas.height = screenH;

  // White background (simulating e-ink)
  ctx.fillStyle = '#f8f8f0';
  ctx.fillRect(0, 0, screenW, screenH);

  // Map image
  if (mapImg && mapImg.complete) {
    ctx.drawImage(mapImg, imgX, imgY);
  }

  // Trash fence pentagon from projected corner points
  drawPentagon();

  // Anchor crosshairs
  ANCHORS.forEach((a, i) => {
    const px = pixelCoords[i];
    if (!px.set) return;
    const isSel = i === selectedIdx;
    ctx.strokeStyle = isSel ? '#e94560' : '#4ecca3';
    ctx.lineWidth = isSel ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(px.x - 14, px.y); ctx.lineTo(px.x + 14, px.y);
    ctx.moveTo(px.x, px.y - 14); ctx.lineTo(px.x, px.y + 14);
    ctx.stroke();
    ctx.beginPath(); ctx.arc(px.x, px.y, isSel ? 7 : 4, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = isSel ? '#e94560' : '#4ecca3';
    ctx.font = '11px monospace';
    ctx.fillText(a[4] || `#${i}`, px.x + 10, px.y - 7);
  });

  // Test points (man, temple, center, plazas)
  const r = projectGPS(0, 0);
  if (r) {
    TEST_POINTS.forEach(tp => {
      const p = projectGPS(tp[0], tp[1]);
      if (!p) return;
      const onScreen = p.x >= 0 && p.x <= screenW && p.y >= 0 && p.y <= screenH;
      if (!onScreen) return;
      ctx.fillStyle = '#f5c518';
      ctx.font = '10px monospace';
      ctx.fillText(tp[2], p.x + 4, p.y - 4);
      ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill();
    });
  }
}

function drawPentagon() {
  // Draw pentagon using projected trash fence points
  if (PENT_POINTS.length < 3) return;
  const pts = [];
  PENT_POINTS.forEach(pp => {
    const p = projectGPS(pp[0], pp[1]);
    if (p) pts.push(p);
  });
  if (pts.length < 3) return;

  // Dotted outline
  ctx.strokeStyle = '#888';
  ctx.lineWidth = 1;
  for (let i = 0; i < pts.length; i++) {
    const s = pts[i], e = pts[(i + 1) % pts.length];
    const d = Math.hypot(e.x - s.x, e.y - s.y);
    const n = Math.max(2, Math.floor(d / 4));
    for (let j = 0; j < n; j++) {
      const t = j / n;
      const x = s.x + t * (e.x - s.x);
      const y = s.y + t * (e.y - s.y);
      ctx.beginPath();
      ctx.moveTo(x, y); ctx.lineTo(x + 1, y);
      ctx.stroke();
    }
  }
}

// ── Projection info ───────────────────────────────────────────
function updateProjection() {
  const r = projectGPS(0, 0);
  const el = document.getElementById('proj-info');
  const tp = document.getElementById('test-points');
  if (!r) {
    el.innerHTML = 'Need ≥2 anchors set';
    tp.innerHTML = '';
    return;
  }
  el.innerHTML = `scale: ${(1/r.scale).toFixed(1)} ft/px &nbsp;|&nbsp; rot: ${r.rot_deg.toFixed(2)}° &nbsp;|&nbsp; origin: (${pixelCoords[0].x},${pixelCoords[0].y})`;

  let html = '';
  TEST_POINTS.forEach(tp => {
    const p = projectGPS(tp[0], tp[1]);
    if (!p) return;
    const on = p.x >= 0 && p.y >= 0 && p.x <= screenW && p.y <= screenH;
    html += `<div style="color:${on ? '#4ecca3' : '#e94560'}">${tp[2]}: (${Math.round(p.x)},${Math.round(p.y)})${on ? '' : ' OFF'}</div>`;
  });
  tp.innerHTML = html;
  drawAll();
}

// ── Click handler ─────────────────────────────────────────────
canvas.addEventListener('click', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = Math.round((e.clientX - rect.left) * screenW / rect.width);
  const sy = Math.round((e.clientY - rect.top) * screenH / rect.height);

  pixelCoords[selectedIdx].x = sx;
  pixelCoords[selectedIdx].y = sy;
  pixelCoords[selectedIdx].set = true;

  document.getElementById(`px-${selectedIdx}`).value = sx;
  document.getElementById(`py-${selectedIdx}`).value = sy;

  buildAnchorUI();
  drawAll();
  updateProjection();
  document.getElementById('status').textContent = `✓ ${ANCHORS[selectedIdx][4]} → (${sx}, ${sy})`;
});

// ── Actions ───────────────────────────────────────────────────
function clearAll() {
  pixelCoords.forEach(p => { p.set = false; });
  buildAnchorUI(); drawAll(); updateProjection();
}

function useDefaults() {
  ANCHORS.forEach((a, i) => {
    pixelCoords[i].x = a[2]; pixelCoords[i].y = a[3]; pixelCoords[i].set = true;
    const x = document.getElementById(`px-${i}`); if (x) x.value = a[2];
    const y = document.getElementById(`py-${i}`); if (y) y.value = a[3];
  });
  buildAnchorUI(); drawAll(); updateProjection();
}

function downloadConfig() {
  const lines = ['# Generated by calibrate.py', 'anchors:'];
  ANCHORS.forEach((a, i) => {
    const px = pixelCoords[i];
    lines.push(`  - [${a[0]}, ${a[1]}, ${px.set ? px.x : 0}, ${px.set ? px.y : 0}]  # ${a[4]}`);
  });

  const blob = new Blob([lines.join('\n') + '\n'], {type: 'text/yaml'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'anchors.yaml';
  a.click();
}

// ── Init ──────────────────────────────────────────────────────
function loadMap() {
  mapImg = new Image();
  mapImg.onload = () => {
    document.getElementById('info').textContent = `Map: ${mapImg.width}×${mapImg.height}`;
    drawAll();
  };
  mapImg.src = MAP_URL;
}

resizeScreen();
buildAnchorUI();
loadMap();
updateProjection();
</script>
</body>
</html>"""


def build_page():
    import yaml

    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: {CONFIG_PATH} not found — run from project root")
        sys.exit(1)

    anchors = cfg["anchors"]
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

    # Trash fence pentagon vertices from GIS (10 points = 9 unique + closing)
    pent_points = [
        [40.779710, -119.237418],
        [40.770250, -119.224998],
        [40.760788, -119.212582],
        [40.766837, -119.196912],
        [40.772884, -119.181240],
        [40.799327, -119.186723],
        [40.801425, -119.204065],
        [40.803521, -119.221408],
        [40.791616, -119.229414],
    ]

    map_path = ROOT / "media" / "Map_1bit.png"
    from PIL import Image

    img = Image.open(map_path)
    map_w, map_h = img.size

    return (
        PAGE.replace("__ANCHORS__", json.dumps(named_anchors))
        .replace("__TEST_POINTS__", json.dumps(test_points))
        .replace("__PENT_POINTS__", json.dumps(pent_points))
        .replace("__TRASH_FENCE_FT__", str(cfg.get("distance_man_to_trashfence_ft", 8479)))
        .replace("__SCREEN_W__", str(cfg["display"]["width"]))
        .replace("__SCREEN_H__", str(cfg["display"]["height"]))
        .replace("__IMAGE_X__", str(cfg["image_position"][0]))
        .replace("__IMAGE_Y__", str(cfg["image_position"][1]))
        .replace("__FEET_PER_DEG__", str(cfg["feet_per_degree"]))
        .replace("__MAP_W__", str(map_w))
        .replace("__MAP_H__", str(map_h))
    )


def serve_map_png():
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
    print("🔧 BRC ePaper Map Calibrator")
    print(f"   Open http://localhost:{port}")
    print(f"   Simulates the full {page_html.count(b'screen')} e-ink screen layout")
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
