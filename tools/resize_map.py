#!/usr/bin/env python3
"""Resize a map PNG to fit the configured e-ink screen dimensions.

Usage:
    python3 tools/resize_map.py [input.png] [--width W] [--height H]

Reads config.yaml for display.width/height and resizes the map to fit
within those bounds, maintaining aspect ratio. Outputs to the configured
map_file path (or specified output).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    import argparse

    import yaml
    from PIL import Image

    # Load config for screen size
    config_path = ROOT / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    screen_w = cfg["display"]["width"]
    screen_h = cfg["display"]["height"]

    parser = argparse.ArgumentParser(description="Resize map PNG to fit e-ink screen")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(ROOT / "media" / "BRC_2026_Map_1bit.png"),
        help="Input PNG file",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "media" / "Map_resized.png"),
        help="Output PNG file",
    )
    parser.add_argument(
        "-W",
        "--width",
        type=int,
        default=screen_w,
        help=f"Target width (default: {screen_w})",
    )
    parser.add_argument(
        "-H",
        "--height",
        type=int,
        default=screen_h,
        help=f"Target height (default: {screen_h})",
    )
    args = parser.parse_args()

    img = Image.open(args.input)
    orig_w, orig_h = img.size
    mode = img.mode
    print(f"Input:  {args.input}  ({orig_w}×{orig_h}, {mode})")

    # Fit within target size maintaining aspect ratio
    scale = min(args.width / orig_w, args.height / orig_h)
    new_w = round(orig_w * scale)
    new_h = round(orig_h * scale)

    # Resize using NEAREST for 1-bit images (preserves sharp edges)
    from PIL.Image import Resampling

    resample = Resampling.NEAREST if mode == "1" else Resampling.LANCZOS
    resized = img.resize((new_w, new_h), resample)

    # Ensure output is 1-bit
    if resized.mode != "1":
        resized = resized.convert("1")

    resized.save(args.output)
    print(f"Output: {args.output}  ({new_w}×{new_h}, {resized.mode})")
    print(f"Scale:  {scale:.3f}  ({orig_w}→{new_w}, {orig_h}→{new_h})")

    # Suggest config updates (bottom-aligned: map touches bottom of screen)
    print()
    print("Suggested config.yaml updates:")
    bottom_y = args.height - new_h
    print(f"  image_position: [{(args.width - new_w) // 2}, {bottom_y}]")
    print(f"  # map_file: \"{Path(args.output).name}\"  (if different from current)")


if __name__ == "__main__":
    main()
