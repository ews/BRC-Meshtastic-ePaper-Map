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
OPEN_PLAYA_MIN_DISTANCE_FT = 700
OPEN_PLAYA_MAX_DISTANCE_FT = 2300
STREET_EDGE_MARGIN_FT = 60
MIN_MARKER_SEPARATION_PX = 24


def _distance_bands(rng, count):
    """Choose city zones, covering open playa and every street at 15 people."""
    open_playa = (
        "Open Playa",
        OPEN_PLAYA_MIN_DISTANCE_FT,
        OPEN_PLAYA_MAX_DISTANCE_FT,
    )
    streets = []
    inner_radius = c.distance_man_esplanade
    for street, width in zip(c.STREET_NAMES, c.DISTANCE_STREETS):
        margin = min(STREET_EDGE_MARGIN_FT, width * 0.2)
        streets.append(
            (street, inner_radius + margin, inner_radius + width - margin)
        )
        inner_radius += width

    if count == 1:
        bands = [open_playa]
    elif count < 1 + len(streets):
        bands = [open_playa, *rng.sample(streets, count - 1)]
    else:
        bands = [open_playa, *streets]
        bands.extend([open_playa] * min(2, count - len(bands)))
        while len(bands) < count:
            bands.append(rng.choice([open_playa, *streets]))
    rng.shuffle(bands)
    return bands


def _clock_value(address):
    """Return the address clock as a number from 0 through 12."""
    clock = address.split(" + ", 1)[0]
    hour, minute = (int(part) for part in clock.split(":"))
    return (hour % 12) + minute / 60


def _city_locations(rng, count):
    """Generate separated GPS locations across open playa and city streets."""
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
            if address.rsplit(" + ", 1)[-1] != expected_zone:
                continue
            on_built_streets = 2 <= _clock_value(address) <= 10
            if expected_zone != "Open Playa" and not on_built_streets:
                continue
            point = gps_to_image_coordinates((lat, lon, "mock burner"))
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
