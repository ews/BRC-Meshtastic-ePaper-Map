"""Configuration loaded from config.yaml with derived values."""

import logging
import os

import geopy
import geopy.distance
import numpy as np
import yaml

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

# --- Map center ---
MAN_LAT = float(_cfg["man_lat"])
MAN_LONG = float(_cfg["man_long"])

# --- BRC geometry ---
distance_man_esplanade = float(_cfg["distance_man_esplanade"])
distance_man_to_end_trashfence_ft = float(_cfg["distance_man_to_end_trashfence_ft"])
DISTANCE_STREETS = _cfg["distance_streets"]
STREET_LAST_LETTER = _cfg["street_last_letter"]
STREET_NAMES = ["Esplanade"] + [
    chr(i) for i in range(ord("A"), ord(STREET_LAST_LETTER) + 1)
]

BRC_NOON = float(_cfg["brc_noon"])

# --- Coordinate conversion ---
ROTATION_ANGLE = float(_cfg["rotation_angle"])
CITY_ANGLE = float(_cfg["city_angle"])
FEET_PER_DEGREE = float(_cfg["feet_per_degree"])

# --- Map image positioning ---
image_position = tuple(_cfg["image_position"])
man_svg = tuple(_cfg["man_svg"])
svg_city_esplanade_radius_pixel = int(_cfg["svg_city_esplanade_radius_pixel"])
svg_city_radius_pixel = int(_cfg["svg_city_radius_pixel"])

# --- Behavior ---
min_distance_refresh_ft = float(_cfg["min_distance_refresh_ft"])

# --- Logging ---
log_file = _cfg["log_file"]

# --- Points of Interest ---
POINTS_OF_INTEREST = _cfg.get("points_of_interest", {})
POI_RADIUS_FT = int(_cfg.get("poi_radius_ft", 50))

# ============================================================
# Derived values — do not edit below this point
# ============================================================

STREET_DISTANCE = 0.002  # unused legacy

svg_city_man_to_trashfence_pixel = (
    distance_man_to_end_trashfence_ft * svg_city_esplanade_radius_pixel
) / distance_man_esplanade

# Screen limits relative to man position
left_limit = man_svg[0] - svg_city_radius_pixel
right_limit = man_svg[0] + svg_city_radius_pixel
top_limit = man_svg[1] - svg_city_man_to_trashfence_pixel
twelve_limit = man_svg[1] - svg_city_radius_pixel
bottom_limit = man_svg[1] + svg_city_radius_pixel

# Landmark pixel positions
temple_svg = (man_svg[0], man_svg[1] - svg_city_esplanade_radius_pixel)
centercamp_svg = (man_svg[0], man_svg[1] + svg_city_esplanade_radius_pixel)

# geopy bounding box
city_radius_ft = distance_man_esplanade + np.sum(DISTANCE_STREETS)
logging.debug("distances %s %s", distance_man_to_end_trashfence_ft, city_radius_ft)
center = geopy.Point(MAN_LAT, MAN_LONG)

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

north = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=0)
east = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=90)
south = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=180)
west = geopy.distance.distance(feet=city_radius_ft).destination(center, bearing=270)

lat_max = north.latitude
lat_min = south.latitude
lon_max = east.longitude
lon_min = west.longitude
