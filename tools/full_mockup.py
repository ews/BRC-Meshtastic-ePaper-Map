#!/usr/bin/env python3
"""Render a full BRC map populated with random mock Meshtastic users."""

import argparse
import math
import random
import sys
import time
from pathlib import Path

from geopy import Point
from geopy.distance import distance as geodesic_distance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as c
from coordinates import gps_to_burning_man, gps_to_image_coordinates
from display_map import _init_epd, _load_map, _new_frame
from renderer import BLACK, BLUE, GREEN, RED, draw_node_labels

MOCK_COLORS = (RED, BLUE, GREEN, BLACK)
DEFAULT_OUTPUT = Path("/tmp/brc-full-mockup.png")
DEFAULT_PEOPLE = 15
NEAR_MAN_MIN_DISTANCE_FT = 700
NEAR_MAN_MAX_DISTANCE_FT = 2300
STREET_EDGE_MARGIN_FT = 60
BEYOND_CITY_MIN_DISTANCE_FT = c.distance_man_esplanade + 250
MIN_MARKER_SEPARATION_PX = 24


def _distance_bands(rng, count):
    """Choose zones covering non-city areas, streets, and trash fence."""
    near_man = (
        "Near Man",
        NEAR_MAN_MIN_DISTANCE_FT,
        NEAR_MAN_MAX_DISTANCE_FT,
    )
    fence_apothem_ft = (
        c.svg_city_man_to_trashfence_pixel
        * math.cos(math.radians(36))
        / c.projection.scale_px_per_ft
    )
    beyond_city = (
        "Beyond City",
        BEYOND_CITY_MIN_DISTANCE_FT,
        fence_apothem_ft - c.trash_fence_proximity_ft - 100,
    )
    trash_fence = (
        "Trash Fence",
        fence_apothem_ft - 500,
        c.distance_man_to_end_trashfence_ft,
    )
    streets = []
    inner_radius = c.distance_man_esplanade
    for street, width in zip(c.STREET_NAMES, c.DISTANCE_STREETS):
        margin = min(STREET_EDGE_MARGIN_FT, width * 0.2)
        streets.append(
            (street, inner_radius + margin, inner_radius + width - margin)
        )
        inner_radius += width

    all_zones = [near_man, beyond_city, trash_fence, *streets]
    if count == 1:
        bands = [near_man]
    elif count < len(all_zones):
        other_zones = rng.sample([beyond_city, trash_fence, *streets], count - 1)
        bands = [near_man, *other_zones]
    else:
        bands = all_zones.copy()
        while len(bands) < count:
            bands.append(rng.choice(all_zones))
    rng.shuffle(bands)
    return bands


def _clock_value(address):
    """Return the address clock as a number from 0 through 12."""
    clock = address.split("+", 1)[0].split(",", 1)[0].split(" and ", 1)[0]
    hour, minute = (int(part) for part in clock.split(":"))
    return (hour % 12) + minute / 60


def _address_zone(address):
    """Return the mock zone represented by a production BRC address."""
    if address.endswith("+Trash Fence"):
        return "Trash Fence"
    if "ft from Man" in address:
        distance_ft = float(address.split(", ", 1)[1].split("ft", 1)[0])
        if distance_ft < c.distance_man_esplanade:
            return "Near Man"
        return "Beyond City"
    return address.rsplit("+", 1)[-1]


def _inside_trash_fence(point):
    """Return whether a projected point is inside the displayed pentagon."""
    cx, cy = c.man_svg
    radius = c.svg_city_man_to_trashfence_pixel
    vertices = []
    for index in range(5):
        angle = math.radians(90 - index * 72)
        vertices.append(
            (cx + radius * math.cos(angle), cy - radius * math.sin(angle))
        )

    x, y = point
    inside = False
    previous = vertices[-1]
    for current in vertices:
        x1, y1 = previous
        x2, y2 = current
        crosses = (y1 > y) != (y2 > y)
        if crosses and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _city_locations(rng, count):
    """Generate separated GPS locations across non-city areas and streets."""
    center = Point(c.MAN_LAT, c.MAN_LONG)
    locations = []
    for expected_zone, minimum_ft, maximum_ft in _distance_bands(rng, count):
        for _ in range(1000):
            bearing = rng.uniform(0, 360)
            distance_ft = math.sqrt(rng.uniform(minimum_ft**2, maximum_ft**2))
            gps = geodesic_distance(feet=distance_ft).destination(
                center, bearing=bearing
            )
            lat, lon = gps.latitude, gps.longitude
            address = gps_to_burning_man(lat, lon)
            if _address_zone(address) != expected_zone:
                continue
            clock_value = _clock_value(address)
            if expected_zone in c.STREET_NAMES and not 2 <= clock_value <= 10:
                continue
            if expected_zone == "Beyond City" and 2 <= clock_value <= 10:
                continue
            point = gps_to_image_coordinates((lat, lon, "mock burner"))
            if not _inside_trash_fence(point):
                continue
            separated = all(
                math.dist(point, existing[2]) >= MIN_MARKER_SEPARATION_PX
                for existing in locations
            )
            if separated:
                locations.append((lat, lon, point))
                break
        else:
            raise RuntimeError(
                f"Could not place a mock burner in {expected_zone} without overlap"
            )
    return locations


def build_mockup(seed=None, people=DEFAULT_PEOPLE, burner_numbers=None):
    """Return an RGB map with mock people distributed across BRC."""
    rng = random.Random(seed)
    count = people
    if not 1 <= count <= 20:
        raise ValueError("people must be between 1 and 20")

    frame, draw = _new_frame(_load_map())
    burners = {}
    numbers = burner_numbers or rng.sample(range(10, 100), count)
    if len(numbers) != count:
        raise ValueError("burner_numbers must match people")
    locations = _city_locations(rng, count)

    for number, (lat, lon, image_coordinates) in zip(numbers, locations):
        name = f"Burner {number}"
        burners[name] = {
            "node_id": f"!mock{number:02d}",
            "coordinates": {
                "latitude": lat,
                "longitude": lon,
                "time": time.time(),
            },
            "bm_coordinates": gps_to_burning_man(lat, lon),
            "image_coordinates": image_coordinates,
        }

    draw_node_labels(burners, draw, colors=MOCK_COLORS)
    return frame, burners


def display_on_epaper(frame):
    """Display a mockup frame on the configured E6 panel, then power it down."""
    epd = _init_epd()
    try:
        print("Displaying mockup on 7.3-inch E6 ePaper...")
        epd.display(epd.getbuffer(frame))
    finally:
        epd.sleep()


def run_mockup(
    *,
    seed=None,
    people=DEFAULT_PEOPLE,
    output=DEFAULT_OUTPUT,
    epaper=False,
    show=True,
    interval=0,
    frames=None,
):
    """Render one mockup or repeatedly move the same burners at an interval."""
    rng = random.Random(seed)
    numbers = rng.sample(range(10, 100), people)
    frame_limit = frames if frames is not None else (None if interval else 1)
    frame_number = 0
    last_burners = None

    while frame_limit is None or frame_number < frame_limit:
        started = time.monotonic()
        layout_seed = rng.getrandbits(64)
        frame, burners = build_mockup(
            seed=layout_seed,
            people=people,
            burner_numbers=numbers,
        )
        frame.save(output)
        frame_number += 1
        last_burners = burners
        print(f"Saved frame {frame_number} with {len(burners)} burners to {output}")
        for name, data in burners.items():
            print(f"  {data['emoji']} {name}: {data['bm_coordinates']}")

        if epaper:
            display_on_epaper(frame)
        elif show:
            frame.show()

        if interval and (frame_limit is None or frame_number < frame_limit):
            elapsed = time.monotonic() - started
            time.sleep(max(0, interval - elapsed))

    return last_burners


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="repeatable random layout")
    parser.add_argument(
        "--people", type=int, default=DEFAULT_PEOPLE, help="number of people"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-show", action="store_true", help="save without opening")
    parser.add_argument(
        "--epaper", action="store_true", help="display on the E6 ePaper panel"
    )
    parser.add_argument(
        "--interval", type=float, default=0, help="seconds between location updates"
    )
    parser.add_argument("--frames", type=int, help="stop after this many frames")
    args = parser.parse_args()

    try:
        run_mockup(
            seed=args.seed,
            people=args.people,
            output=args.output,
            epaper=args.epaper,
            show=not args.no_show,
            interval=args.interval,
            frames=args.frames,
        )
    except KeyboardInterrupt:
        print("\nMockup stopped.")


if __name__ == "__main__":
    main()
