"""Coordinate conversions between GPS, Burning Man addresses, and screen pixels."""

import math

from geopy.distance import geodesic as GD

import config as c

logging = c.logging

# --- Bounds for sanity checking ---
# BRC is roughly within 1° of The Man
_MAX_DEGREES_FROM_MAN = 1.0


def distance_ft(a, b):
    """Distance in feet between two (lat, lon) tuples."""
    return GD(a, b).ft


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Compass bearing from point 1 to point 2, in degrees (0–360)."""
    d_lon = math.radians(lon2 - lon1)
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)

    x = math.sin(d_lon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
        lat2_r
    ) * math.cos(d_lon)

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _validate_coords(lat, lon):
    """Check that coordinates are plausible (near BRC)."""
    if abs(lat - c.MAN_LAT) > _MAX_DEGREES_FROM_MAN:
        logging.warning("latitude %.6f is far from BRC center (%.6f)", lat, c.MAN_LAT)
    if abs(lon - c.MAN_LONG) > _MAX_DEGREES_FROM_MAN:
        logging.warning("longitude %.6f is far from BRC center (%.6f)", lon, c.MAN_LONG)


def _point_to_segment_distance(point, start, end):
    """Return the Euclidean distance from a point to a line segment."""
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    fraction = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    fraction = max(0.0, min(1.0, fraction))
    closest = (x1 + fraction * dx, y1 + fraction * dy)
    return math.hypot(px - closest[0], py - closest[1])


def distance_to_trash_fence_ft(lat, lon):
    """Return distance in feet to the displayed trash-fence pentagon."""
    cx, cy = c.man_svg
    radius = c.svg_city_man_to_trashfence_pixel
    vertices = []
    for index in range(5):
        angle = math.radians(90 - index * 72)
        vertices.append(
            (cx + radius * math.cos(angle), cy - radius * math.sin(angle))
        )

    point = c.projection.gps_to_pixel(lat, lon)
    distance_px = min(
        _point_to_segment_distance(point, vertices[index - 1], vertices[index])
        for index in range(5)
    )
    return distance_px / c.projection.scale_px_per_ft


def gps_to_burning_man(lat, lon):
    """Convert GPS coordinates to a Burning Man address string.

    Returns e.g. "09:30+Esplanade" or "12:00+Temple" for known POIs.
    """

    _validate_coords(lat, lon)

    distance = GD((c.MAN_LAT, c.MAN_LONG), (lat, lon)).feet

    angle_deg = _bearing_deg(c.MAN_LAT, c.MAN_LONG, lat, lon)
    angle_rad = math.radians(angle_deg)

    # Convert bearing to clock face
    rad_to_hour = 6.0 / math.pi
    bearing_to_man = angle_rad * rad_to_hour
    bearing_to_man += 12.0 - c.BRC_NOON
    if bearing_to_man > 12.0:
        bearing_to_man -= 12.0

    clock_hour = int(bearing_to_man)
    clock_minutes = int((bearing_to_man - int(bearing_to_man)) * 60.0)
    if clock_hour == 0:
        clock_hour = 12

    str_clock_hour = f"{clock_hour:02d}"
    str_clock_minutes = f"{clock_minutes:02d}"
    clock = f"{str_clock_hour}:{str_clock_minutes}"

    # Check known POIs before applying general location labels.
    for name, info in c.POINTS_OF_INTEREST.items():
        expected_dist = float(info["distance_from_man_ft"])
        if abs(distance - expected_dist) < c.POI_RADIUS_FT:
            return info.get("clock", "") + "+" + name

    if distance_to_trash_fence_ft(lat, lon) <= c.trash_fence_proximity_ft:
        return f"{clock}+Trash Fence"

    # Street names apply only to the built 2:00–10:00 city rings.
    remaining_distance = distance - c.distance_man_esplanade
    clock_value = (clock_hour % 12) + clock_minutes / 60
    if remaining_distance >= 0 and 2 <= clock_value <= 10:
        for index, street_distance in enumerate(c.DISTANCE_STREETS):
            if remaining_distance < street_distance:
                return f"{clock}+{c.STREET_NAMES[index]}"
            remaining_distance -= street_distance

    return f"{clock}, {distance:.0f}ft from Man"


def gps_to_image_coordinates(coord):
    """Convert (lat, lon, name) to (x, y) screen pixel coordinates.

    Uses the MapProjection configured from anchor points in config.yaml.
    """
    latitude = coord[0]
    longitude = coord[1]
    point_name = coord[2]

    _validate_coords(latitude, longitude)

    px, py = c.projection.gps_to_pixel(latitude, longitude)

    logging.debug("project %s -> (%.1f, %.1f)", point_name, px, py)

    # Clamp to screen bounds
    x = max(0, min(c.WIDTH - 1, int(round(px))))
    y = max(0, min(c.HEIGHT - 1, int(round(py))))

    return (x, y)
