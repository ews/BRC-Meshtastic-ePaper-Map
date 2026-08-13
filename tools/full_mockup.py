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


def build_mockup(seed=None, people=None):
    """Return an RGB map and 5–6 randomly positioned mock people."""
    rng = random.Random(seed)
    count = people if people is not None else rng.randint(5, 6)
    if not 1 <= count <= 20:
        raise ValueError("people must be between 1 and 20")

    frame, draw = _new_frame(_load_map())
    burners = {}
    numbers = rng.sample(range(10, 100), count)

    for number in numbers:
        # Keep markers on the populated horseshoe visible in the map artwork,
        # roughly 3,400–4,500 ft from The Man with the current calibration.
        angle = rng.uniform(0.05 * math.pi, 0.95 * math.pi)
        radius_px = rng.uniform(140, 185)
        x = c.man_svg[0] + math.cos(angle) * radius_px
        y = c.man_svg[1] + math.sin(angle) * radius_px
        lat, lon = c.projection.pixel_to_gps(round(x), round(y))
        name = f"Burner {number}"
        burners[name] = {
            "node_id": f"!mock{number:02d}",
            "coordinates": {
                "latitude": lat,
                "longitude": lon,
                "time": time.time(),
            },
            "bm_coordinates": gps_to_burning_man(lat, lon),
            "image_coordinates": (round(x), round(y)),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="repeatable random layout")
    parser.add_argument("--people", type=int, help="number of people (default: 5–6)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-show", action="store_true", help="save without opening")
    parser.add_argument(
        "--epaper", action="store_true", help="display on the E6 ePaper panel"
    )
    args = parser.parse_args()

    frame, burners = build_mockup(seed=args.seed, people=args.people)
    frame.save(args.output)
    print(f"Saved {len(burners)}-person mockup to {args.output}")
    for name, data in burners.items():
        print(f"  {name}: {data['bm_coordinates']}")

    if args.epaper:
        display_on_epaper(frame)
    elif not args.no_show:
        frame.show()


if __name__ == "__main__":
    main()
