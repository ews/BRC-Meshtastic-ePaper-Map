#!/usr/bin/env python3
"""Display a JPG or PNG image on the WaveShare 7.3-inch E6 e-paper panel.

The image is scaled to 480x800 (portrait canvas) and the driver rotates it
90 degrees to fill the landscape-mounted 800x480 panel.

Usage:
    python tools/display_image.py photo.jpg
    python tools/display_image.py converted_e6.png --fit contain
    python tools/display_image.py --clear          # blank the screen
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from tools.convert_image import quantize_e6, resize_to_fit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", help="input JPG/PNG file")
    parser.add_argument(
        "--fit",
        choices=("cover", "contain"),
        default="cover",
        help="cover crops to fill, contain letterboxes (default cover)",
    )
    parser.add_argument(
        "--no-dither",
        action="store_true",
        help="disable Floyd-Steinberg dithering",
    )
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help="keep the panel awake after displaying",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="blank the screen to white and exit",
    )
    return parser


def display(image: Image.Image | None, no_sleep: bool = False) -> int:
    """Write one quantized image to the E6 panel. Returns exit code."""
    if (
        importlib.util.find_spec("RPi") is None
        or importlib.util.find_spec("RPi.GPIO") is None
    ):
        print("ERROR: RPi.GPIO not found — this only works on a Raspberry Pi.")
        return 1

    from waveshare_epd import epd7in3e

    epd = epd7in3e.EPD()
    print("Initializing ePaper...")
    if epd.init() != 0:
        print("ERROR: ePaper init failed — check SPI connection and wiring.")
        return 1

    if image is None:
        print("Clearing screen...")
        epd.Clear()
    else:
        print(f"Displaying {image.width}x{image.height}...")
        epd.display(epd.getbuffer(image))

    if not no_sleep:
        print("Done — panel sleeping")
        epd.sleep()
    else:
        print("Done")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.clear:
        return display(None, no_sleep=True)

    if not args.image:
        print("error: an image path is required (or use --clear)", file=sys.stderr)
        return 1

    source = Path(args.image)
    if not source.is_file():
        print(f"error: {source} not found", file=sys.stderr)
        return 1

    with Image.open(source) as img:
        resized = resize_to_fit(img, 480, 800, args.fit)
        indexed = quantize_e6(resized, not args.no_dither)

    return display(indexed, no_sleep=args.no_sleep)


if __name__ == "__main__":
    raise SystemExit(main())
