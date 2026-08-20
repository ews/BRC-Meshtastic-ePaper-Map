#!/usr/bin/env python3
"""Convert any image to the 6-color 480x800 E6 e-paper palette.

The panel is mounted in landscape (buffer 800x480); images are prepared at
480x800 and the driver rotates them 90 degrees on display.

Usage:
    python tools/convert_image.py photo.jpg
    python tools/convert_image.py photo.jpg --output out.png --fit contain
    python tools/convert_image.py photo.png --width 800 --height 480
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from e6_convert import quantize_e6, resize_to_fit


def convert(
    source: Path,
    output: Path,
    width: int,
    height: int,
    fit: str,
    dither: bool,
) -> None:
    """Convert one image file to the E6 palette and save it."""
    with Image.open(source) as img:
        resized = resize_to_fit(img, width, height, fit)
        indexed = quantize_e6(resized, dither)

    # Save in a format that keeps the 256-entry palette intact.
    indexed.save(output, format="PNG")
    colors = indexed.getcolors(256)
    color_count = len(colors) if colors else 256
    print(f"Saved {output} ({indexed.width}x{indexed.height}, {color_count} colors)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="input JPG/PNG file")
    parser.add_argument("-o", "--output", help="output PNG (default: <stem>_e6.png)")
    parser.add_argument(
        "-W", "--width", type=int, default=480, help="target width (default 480)"
    )
    parser.add_argument(
        "-H", "--height", type=int, default=800, help="target height (default 800)"
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.image)
    if not source.is_file():
        print(f"error: {source} not found", file=sys.stderr)
        return 1

    output = (
        Path(args.output) if args.output else source.with_name(f"{source.stem}_e6.png")
    )
    convert(source, output, args.width, args.height, args.fit, not args.no_dither)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
