"""Shared E6 e-paper image helpers: palette, resize, and quantization.

Used by tools/convert_image.py and tools/display_image.py so both produce
identical output for the same input image.
"""

from __future__ import annotations

from PIL import Image

# E6/Spectra 6 palette, index order must match epd7in3e.EPD.getbuffer().
# Index 4 is an unused hardware slot rendered as black.
E6_COLORS = (
    (0, 0, 0),  # 0: BLACK
    (255, 255, 255),  # 1: WHITE
    (255, 255, 0),  # 2: YELLOW
    (255, 0, 0),  # 3: RED
    (0, 0, 0),  # 4: (unused -> black)
    (0, 0, 255),  # 5: BLUE
    (0, 255, 0),  # 6: GREEN
)

E6_PALETTE = (
    tuple(channel for color in E6_COLORS for channel in color)
    + (
        0,
        0,
        0,
    )
    * 249
)


def resize_to_fit(img: Image.Image, width: int, height: int, fit: str) -> Image.Image:
    """Scale an image to exactly width x height using cover or contain."""
    if img.size == (width, height):
        return img.convert("RGB")

    src_ratio = img.width / img.height
    dst_ratio = width / height

    if (fit == "cover" and src_ratio > dst_ratio) or (
        fit == "contain" and src_ratio <= dst_ratio
    ):
        # Scale by height, then crop or pad horizontally
        new_h = height
        new_w = round(height * src_ratio)
    else:
        # Scale by width, then crop or pad vertically
        new_w = width
        new_h = round(width / src_ratio)

    scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if fit == "cover":
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        return scaled.crop((left, top, left + width, top + height))

    # contain: letterbox on white (white = palette index 1)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    left = (width - new_w) // 2
    top = (height - new_h) // 2
    canvas.paste(scaled, (left, top))
    return canvas


def quantize_e6(img: Image.Image, dither: bool = True) -> Image.Image:
    """Quantize an RGB image to the E6 six-color palette."""
    palette = Image.new("P", (1, 1))
    palette.putpalette(E6_PALETTE)
    return img.quantize(
        palette=palette,
        dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE,
    )
