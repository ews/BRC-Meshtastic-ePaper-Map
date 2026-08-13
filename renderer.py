"""PIL drawing helpers for the ePaper map display.

Functions for drawing dots, the trash fence pentagon, node labels,
and the debug test coordinate overlay.
"""

import math

from PIL import ImageFont

import config as c
from burner_emojis import default_emoji
from coordinates import gps_to_burning_man, gps_to_image_coordinates

logging = c.logging

# Native colors supported by the E6/Spectra 6 panel.
BLACK = (0, 0, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)

# --- test coordinates from official 2026 GIS data ---
# Source: innovate-GIS-data/2026/GeoJSON/
_TEST_COORDS = [
    [40.783247, -119.207884, "man"],  # The Man
    [40.788099, -119.201500, "temple"],  # The Temple
    [40.777372, -119.215612, "center"],  # Center Camp
    [40.792611, -119.220207, "9G"],  # 9:00 & G
    [40.783245, -119.225308, "730G"],  # 7:30 & G
    [40.770004, -119.207883, "430G"],  # 4:30 & G
    [40.773883, -119.195565, "3G"],  # 3:00 & G
    [40.779710, -119.237418, "pt1"],  # fence v1
    [40.803521, -119.221408, "pt2"],  # fence v2
    [40.799288, -119.186672, "pt3"],  # fence v3
    [40.772884, -119.181240, "pt4"],  # fence v4
    [40.760788, -119.212582, "pt5"],  # fence v5
]


def draw_dot(draw, coord, radius=5, fill_color=RED):
    """Draw a filled circle at the given (x, y) pixel coordinate."""
    x, y = coord
    draw.ellipse([(x - radius, y - radius), (x + radius, y + radius)], fill=fill_color)


def draw_upward_pentagon(draw, center, radius, outline_color=RED, fill_color=None):
    """Draw a dotted upward-pointing pentagon (trash fence outline)."""
    pentagon = []
    for i in range(5):
        angle = math.radians(90 - i * 72)
        x = center[0] + radius * math.cos(angle)
        y = center[1] - radius * math.sin(angle)
        pentagon.append((x, y))

    draw.polygon(pentagon, outline=None, fill=fill_color)

    dot_spacing = 4
    for i in range(5):
        start = pentagon[i]
        end = pentagon[(i + 1) % 5]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = math.hypot(dx, dy)
        num_dots = max(1, int(dist / dot_spacing))
        for j in range(num_dots):
            x = start[0] + j / num_dots * dx
            y = start[1] + j / num_dots * dy
            draw.line([(x, y), (x + 1, y)], fill=outline_color)

    return draw


def assign_burner_emojis(burners):
    """Assign stable, distinct symbols to the visible burners when possible."""
    used = set()
    ordered = sorted(
        burners.items(), key=lambda item: item[1].get("node_id", item[0])
    )
    for name, burner in ordered:
        if burner.get("emoji"):
            used.add(burner["emoji"])
            continue
        identity = burner.get("node_id", name)
        emoji = default_emoji(identity, used)
        burner["emoji"] = emoji
        used.add(emoji)
    return burners


def draw_node_labels(burners, draw, colors=None):
    """Draw matching emoji markers and detail-list entries for all burners."""
    font = ImageFont.truetype("./media/Font.ttc", 12)
    map_font = ImageFont.truetype("./media/Font.ttc", 18)
    text_start_height = 20
    colors = colors or (RED,)
    assign_burner_emojis(burners)

    for index, name in enumerate(burners):
        burner = burners[name]
        color = colors[index % len(colors)]
        emoji = burner["emoji"]
        x, y = burner["image_coordinates"]
        draw.ellipse(
            [(x - 10, y - 10), (x + 10, y + 10)],
            fill="white",
            outline=color,
            width=2,
        )
        draw.text((x, y), emoji, font=map_font, fill=color, anchor="mm")

        detail = (
            f"{emoji} {name}: {burner['bm_coordinates']} "
            f"at {_time_str(burner['coordinates']['time'])}"
        )
        draw.text((10, text_start_height), detail, font=font, fill=color)
        text_start_height += 14

    return draw


def draw_test_coordinates(draw, calibrate=False):
    """Draw labeled test points for calibration/debug."""
    font = ImageFont.truetype("./media/Font.ttc", 12)

    for lat, lon, name in _TEST_COORDS:
        addr = gps_to_burning_man(lat, lon)
        px = gps_to_image_coordinates((lat, lon, name))

        if calibrate:
            logging.info(
                "CALIB %6s | GPS=(%.6f,%.6f) | BRC=%s | pixel=(%d,%d) | screen=%s",
                name,
                lat,
                lon,
                addr,
                px[0],
                px[1],
                "in"
                if (
                    c.left_limit <= px[0] <= c.right_limit
                    and c.twelve_limit <= px[1] <= c.bottom_limit
                )
                else "OFF",
            )

        draw.text(px, name, font=font, fill=BLACK)

    return draw


def _time_str(timestamp):
    """Format a Unix timestamp as HH:MM:SS."""
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
