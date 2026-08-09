#!/usr/bin/env python3
"""Test the WaveShare ePaper display — clears screen and draws a test pattern.

Useful for verifying hardware connection on a Raspberry Pi.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw


def test_screen():
    """Test the ePaper display. Requires Raspberry Pi with SPI enabled."""
    print("Testing ePaper display (Raspberry Pi only)...")

    import importlib.util

    if importlib.util.find_spec("RPi.GPIO") is None:
        print("ERROR: RPi.GPIO not found — this test only works on a Raspberry Pi.")
        print("On your laptop, use: make test")
        return

    from waveshare_epd import epd7in5_V2

    epd = epd7in5_V2.EPD()
    print("Initializing...")
    if epd.init() != 0:
        print("ERROR: ePaper init failed — check SPI connection and wiring.")
        return

    # Clear screen
    print("Clearing screen...")
    epd.Clear()

    # Draw test pattern
    img = Image.new("1", (epd.width, epd.height), 255)
    draw = ImageDraw.Draw(img)

    # Border
    draw.rectangle([0, 0, epd.width - 1, epd.height - 1], outline=0, width=3)
    draw.rectangle([5, 5, epd.width - 6, epd.height - 6], outline=0, width=1)

    # Crosshair
    cx, cy = epd.width // 2, epd.height // 2
    draw.line([cx - 50, cy, cx + 50, cy], fill=0, width=2)
    draw.line([cx, cy - 50, cx, cy + 50], fill=0, width=2)

    # Text
    draw.text((cx - 80, cy - 80), "BRC Meshtastic Map", fill=0)
    draw.text((cx - 50, cy + 60), f"{epd.width}x{epd.height}", fill=0)
    draw.text((cx - 20, cy + 80), "ePaper OK", fill=0)

    print("Drawing test pattern...")
    epd.display(epd.getbuffer(img))

    print("Done")
    epd.sleep()


if __name__ == "__main__":
    test_screen()
