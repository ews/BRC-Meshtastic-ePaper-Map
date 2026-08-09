#!/usr/bin/env python3
"""Test the WaveShare ePaper display — clears screen and draws a test pattern.

Useful for verifying hardware connection on a Raspberry Pi.
"""

from PIL import Image, ImageDraw


def test_screen():
    from waveshare_epd import epd7in5b_V2

    epd = epd7in5b_V2.EPD()
    print("Initializing ePaper...")
    epd.init()

    # Clear both layers
    print("Clearing screen...")
    epd.Clear()

    # Draw a test pattern: black border + text
    black = Image.new("1", (epd.width, epd.height), 255)
    red = Image.new("1", (epd.width, epd.height), 255)
    draw_b = ImageDraw.Draw(black)
    draw_r = ImageDraw.Draw(red)

    # Border
    draw_b.rectangle([0, 0, epd.width - 1, epd.height - 1], outline=0, width=3)
    draw_b.rectangle([5, 5, epd.width - 6, epd.height - 6], outline=0, width=1)

    # Crosshair
    cx, cy = epd.width // 2, epd.height // 2
    draw_r.line([cx - 50, cy, cx + 50, cy], fill=0, width=2)
    draw_r.line([cx, cy - 50, cx, cy + 50], fill=0, width=2)

    # Text on red layer
    text = "BRC Meshtastic Map"
    draw_r.text((cx - 80, cy - 80), text, fill=0)
    draw_b.text((cx - 50, cy + 60), f"{epd.width}x{epd.height}", fill=0)
    draw_b.text((cx - 20, cy + 80), "ePaper OK", fill=0)

    print("Drawing test pattern...")
    epd.display(epd.getbuffer(black), epd.getbuffer(red))

    print("Done — screen should show border + crosshair")
    epd.sleep()


if __name__ == "__main__":
    test_screen()
