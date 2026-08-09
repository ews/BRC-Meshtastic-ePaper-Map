#!/usr/bin/env python3
"""Generate a 1-bit BRC map PNG from 2026 GIS GeoJSON data.

Uses the same projection math as projection.py to ensure the generated map
aligns with the anchor-point calibration system.
"""

import json
import math
from pathlib import Path

GIS_DIR = Path("/home/ews/sources/innovate-GIS-data/2026/GeoJSON")
OUTPUT = Path("media/Map_1bit.png")

# Output size (match current config: 480×800 screen, map pasted at [6,400])
MAP_W = 465
MAP_H = 371

# BRC center (The Man)
MAN_LAT = 40.783247
MAN_LON = -119.207884
FEET_PER_DEG = 364000


def gps_to_ft(lat, lon):
    """Convert GPS to local feet (east, north) from The Man."""
    cos_lat = math.cos(math.radians(MAN_LAT))
    dx = (lon - MAN_LON) * FEET_PER_DEG * cos_lat
    dy = (lat - MAN_LAT) * FEET_PER_DEG
    return dx, dy


def render_map():
    from PIL import Image, ImageDraw

    # Load all GIS layers
    layers = {}
    for name in [
        "trash_fence",
        "street_lines",
        "street_outlines",
        "city_blocks",
        "plazas",
        "gate_road",
        "dmz",
        "toilets",
        "cpns",
    ]:
        with open(GIS_DIR / f"{name}.geojson") as f:
            layers[name] = json.load(f)

    # Determine bounding box from trash fence (covers entire BRC)
    fence_coords = layers["trash_fence"]["features"][0]["geometry"]["coordinates"][0]
    all_lons = [c[0] for c in fence_coords]
    all_lats = [c[1] for c in fence_coords]

    # Also include gate road and DMZ for full extent
    for feat in layers["gate_road"]["features"]:
        for lon, lat in feat["geometry"]["coordinates"]:
            all_lons.append(lon)
            all_lats.append(lat)

    lat_min, lat_max = min(all_lats), max(all_lats)
    lon_min, lon_max = min(all_lons), max(all_lons)

    # Convert corners to feet
    corners = [
        gps_to_ft(lat, lon)
        for lat, lon in zip(
            [lat_min, lat_max, lat_max, lat_min],
            [lon_min, lon_max, lon_min, lon_max],
        )
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)

    # Add 5% padding
    pad_x = (x_max - x_min) * 0.05
    pad_y = (y_max - y_min) * 0.05
    x_min -= pad_x
    x_max += pad_x
    y_min -= pad_y
    y_max += pad_y

    # Scale to fit MAP_W × MAP_H preserving aspect ratio
    data_w = x_max - x_min
    data_h = y_max - y_min
    scale = min(MAP_W / data_w, MAP_H / data_h)
    # Center in the output
    offset_x = (MAP_W - data_w * scale) / 2
    offset_y = (MAP_H - data_h * scale) / 2

    def to_px(lat, lon):
        x_ft, y_ft = gps_to_ft(lat, lon)
        px = offset_x + (x_ft - x_min) * scale
        # Flip y: GIS north = up, PIL y = down
        py = MAP_H - (offset_y + (y_ft - y_min) * scale)
        return px, py

    # Create image
    img = Image.new("1", (MAP_W, MAP_H), 1)  # 1 = white
    draw = ImageDraw.Draw(img)

    # ── Layer 1: City blocks (filled black) ─────────────────────
    for feat in layers["city_blocks"]["features"]:
        rings = feat["geometry"]["coordinates"]
        for ring in rings:
            pts = [to_px(lat, lon) for lon, lat in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=0)

    # ── Layer 2: Street centerlines ─────────────────────────────
    for feat in layers["street_lines"]["features"]:
        coords = feat["geometry"]["coordinates"]
        pts = [to_px(lat, lon) for lon, lat in coords]
        if len(pts) >= 2:
            draw.line(pts, fill=1, width=2)  # white lines = streets

    # ── Layer 3: Plazas (white circles) ─────────────────────────
    for feat in layers["plazas"]["features"]:
        ring = feat["geometry"]["coordinates"][0]
        pts = [to_px(lat, lon) for lon, lat in ring]
        if len(pts) >= 3:
            draw.polygon(pts, fill=1)

    # ── Layer 4: Trash fence (dashed outline) ───────────────────
    ring = layers["trash_fence"]["features"][0]["geometry"]["coordinates"][0]
    pts = [to_px(lat, lon) for lon, lat in ring]
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dist = math.hypot(x2 - x1, y2 - y1)
        num_dots = max(1, int(dist / 3))
        for j in range(num_dots):
            t = j / num_dots
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            draw.point((int(x), int(y)), fill=0)

    # ── Layer 5: Gate road ──────────────────────────────────────
    for feat in layers["gate_road"]["features"]:
        coords = feat["geometry"]["coordinates"]
        pts = [to_px(lat, lon) for lon, lat in coords]
        if len(pts) >= 2:
            draw.line(pts, fill=0, width=1)

    # ── Layer 6: DMZ outline ────────────────────────────────────
    for feat in layers["dmz"]["features"]:
        ring = feat["geometry"]["coordinates"][0]
        pts = [to_px(lat, lon) for lon, lat in ring]
        if len(pts) >= 3:
            draw.polygon(pts, outline=0, fill=1)

    # ── Layer 7: The Man marker (small black cross) ─────────────
    mx, my = to_px(MAN_LAT, MAN_LON)
    r = 3
    draw.line([(mx - r, my), (mx + r, my)], fill=0, width=1)
    draw.line([(mx, my - r), (mx, my + r)], fill=0, width=1)

    # ── Save ────────────────────────────────────────────────────
    img.save(OUTPUT)
    print(f"Saved {OUTPUT} ({MAP_W}×{MAP_H})")
    print(
        f"  Bounds: lat [{lat_min:.4f}, {lat_max:.4f}]  lon [{lon_min:.4f}, {lon_max:.4f}]"
    )
    print(f"  Scale: {1 / scale:.0f} ft/px")
    print(f"  The Man at pixel: ({mx:.0f}, {my:.0f})")


if __name__ == "__main__":
    render_map()
