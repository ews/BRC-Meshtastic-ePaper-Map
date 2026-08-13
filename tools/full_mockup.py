#!/usr/bin/env python3
"""Render a full BRC map populated with random mock Meshtastic users."""

import argparse
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as c
from coordinates import gps_to_burning_man
from display_map import _init_epd, _load_map, _new_frame
from renderer import BLACK, BLUE, GREEN, RED, draw_node_labels

MOCK_COLORS = (RED, BLUE, GREEN, BLACK)
DEFAULT_OUTPUT = Path("/tmp/brc-full-mockup.png")
DEFAULT_PEOPLE = 15
OPEN_PLAYA_MIN_RADIUS_PX = 28
OPEN_PLAYA_MAX_RADIUS_PX = 96
MIN_MARKER_SEPARATION_PX = 24


def _open_playa_points(rng, count):
    """Choose separated marker positions inside the open-playa circle."""
    points = []
    attempts = 0
    while len(points) < count and attempts < 5000:
        attempts += 1
        angle = rng.uniform(0, 2 * math.pi)
        radius = math.sqrt(
            rng.uniform(
                OPEN_PLAYA_MIN_RADIUS_PX**2,
                OPEN_PLAYA_MAX_RADIUS_PX**2,
            )
        )
        point = (
            round(c.man_svg[0] + math.cos(angle) * radius),
            round(c.man_svg[1] + math.sin(angle) * radius),
        )
        separated = all(
            math.dist(point, existing) >= MIN_MARKER_SEPARATION_PX
            for existing in points
        )
        if separated:
            points.append(point)
    if len(points) != count:
        raise RuntimeError("Could not place all mock burners without overlap")
    return points


def build_mockup(seed=None, people=DEFAULT_PEOPLE, burner_numbers=None):
    """Return an RGB map with mock people positioned on open playa."""
    rng = random.Random(seed)
    count = people
    if not 1 <= count <= 20:
        raise ValueError("people must be between 1 and 20")

    frame, draw = _new_frame(_load_map())
    burners = {}
    numbers = burner_numbers or rng.sample(range(10, 100), count)
    if len(numbers) != count:
        raise ValueError("burner_numbers must match people")
    points = _open_playa_points(rng, count)

    for number, (x, y) in zip(numbers, points):
        lat, lon = c.projection.pixel_to_gps(x, y)
        name = f"Burner {number}"
        burners[name] = {
            "node_id": f"!mock{number:02d}",
            "coordinates": {
                "latitude": lat,
                "longitude": lon,
                "time": time.time(),
            },
            "bm_coordinates": gps_to_burning_man(lat, lon),
            "image_coordinates": (x, y),
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
