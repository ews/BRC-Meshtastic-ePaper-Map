"""Configuration loaded from config.yaml with MapProjection."""

import logging
import os

import yaml

from projection import MapProjection

# --- Load user configuration ---
_config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(_config_path) as f:
    _cfg = yaml.safe_load(f)

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("debug.log"), logging.StreamHandler()],
)

# --- Display ---
WIDTH = _cfg["display"]["width"]
HEIGHT = _cfg["display"]["height"]

# --- Polling ---
sleep_seconds = _cfg["sleep_seconds"]

# --- Map image placement ---
image_position = tuple(_cfg["image_position"])

# --- GPS → Screen projection ---
FEET_PER_DEGREE = float(_cfg["feet_per_degree"])
_anchors = [
    (float(lat), float(lon), float(px), float(py))
    for lat, lon, px, py in _cfg["anchors"]
]
projection = MapProjection(_anchors, feet_per_degree=FEET_PER_DEGREE)

# Convenience: get origin as module-level for backward compatibility
man_lat, man_lon = projection.origin_gps
MAN_LAT = man_lat
MAN_LONG = man_lon
man_svg = tuple(int(round(v)) for v in projection.origin_px)

# --- BRC geometry (for gps_to_burning_man address display) ---
_brc = _cfg["brc"]
MAN_LAT = float(_brc["man_lat"])
MAN_LONG = float(_brc["man_long"])
distance_man_esplanade = float(_brc["distance_man_esplanade"])
DISTANCE_STREETS = _brc["distance_streets"]
STREET_LAST_LETTER = _brc["street_last_letter"]
STREET_NAMES = ["Esplanade"] + [
    chr(i) for i in range(ord("A"), ord(STREET_LAST_LETTER) + 1)
]
BRC_NOON = float(_brc["brc_noon"])

# Street distance constant (unused legacy)
STREET_DISTANCE = 0.002

# --- Behavior ---
min_distance_refresh_ft = float(_cfg["min_distance_refresh_ft"])
log_file = _cfg["log_file"]

# --- Points of Interest ---
POINTS_OF_INTEREST = _cfg.get("points_of_interest", {})
POI_RADIUS_FT = int(_cfg.get("poi_radius_ft", 50))

# --- Trash fence (for debug pentagon drawing) ---
distance_man_to_end_trashfence_ft = float(_cfg["distance_man_to_trashfence_ft"])
_trash_px = _cfg.get("trash_fence_radius_px")
if _trash_px is not None:
    svg_city_man_to_trashfence_pixel = float(_trash_px)
else:
    # Compute from projection scale
    svg_city_man_to_trashfence_pixel = (
        distance_man_to_end_trashfence_ft * projection.scale_px_per_ft
    )

# Legacy derived values kept for display_map.py debug drawings
# These will be gradually phased out in favor of projection.gps_to_pixel()
city_radius_ft = distance_man_esplanade + sum(DISTANCE_STREETS)
logging.debug("distances %s %s", distance_man_to_end_trashfence_ft, city_radius_ft)

# Bounding box (used only by legacy gps_to_image_coordinates)
import geopy
import geopy.distance

center = geopy.Point(MAN_LAT, MAN_LONG)
north = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=0)
east = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=90)
south = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=180)
west = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=270)
lat_max = north.latitude
lat_min = south.latitude
lon_max = east.longitude
lon_min = west.longitude

top_trash_fence = geopy.distance.distance(
    feet=distance_man_to_end_trashfence_ft
).destination(center, bearing=45)
twelve_city = geopy.distance.distance(feet=city_radius_ft).destination(
    center, bearing=45
)
bottom_city = geopy.distance.distance(feet=city_radius_ft).destination(
    center, bearing=225
)
top_trash_fence_screen = (800, 0)
bottom_city_screen = (0, 480)

# Screen limits for debug
_svg_espl = float(
    _cfg.get("svg_city_esplanade_radius_px", projection.scale_px_per_ft * 2500.0)
)
_svg_city = float(
    _cfg.get("svg_city_radius_px", projection.scale_px_per_ft * city_radius_ft)
)
svg_city_esplanade_radius_pixel = int(_svg_espl)
svg_city_radius_pixel = int(_svg_city)

left_limit = man_svg[0] - svg_city_radius_pixel
right_limit = man_svg[0] + svg_city_radius_pixel
top_limit = man_svg[1] - int(svg_city_man_to_trashfence_pixel)
twelve_limit = man_svg[1] - svg_city_radius_pixel
bottom_limit = man_svg[1] + svg_city_radius_pixel

temple_svg = (man_svg[0], man_svg[1] - svg_city_esplanade_radius_pixel)
centercamp_svg = (man_svg[0], man_svg[1] + svg_city_esplanade_radius_pixel)
