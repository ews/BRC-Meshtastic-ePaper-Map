"""Tests for the WaveShare 7.3-inch E6 framebuffer conversion."""

from PIL import Image
import pytest

from waveshare_epd import epd7in3e, epdconfig


def test_getbuffer_packs_e6_palette_indexes():
    epd = epd7in3e.EPD()
    image = Image.new("RGB", (epd.width, epd.height), "white")
    colors = [
        (0, 0, 0),
        (255, 255, 255),
        (255, 255, 0),
        (255, 0, 0),
        (0, 0, 255),
        (0, 255, 0),
    ]
    for x, color in enumerate(colors):
        image.putpixel((x, 0), color)

    buffer = epd.getbuffer(image)

    assert len(buffer) == epd.width * epd.height // 2
    assert buffer[:3] == bytearray((0x01, 0x23, 0x56))


def test_getbuffer_accepts_portrait_application_frame():
    epd = epd7in3e.EPD()
    image = Image.new("RGB", (epd.height, epd.width), "white")

    assert len(epd.getbuffer(image)) == epd.width * epd.height // 2


def test_getbuffer_rejects_wrong_dimensions():
    epd = epd7in3e.EPD()

    with pytest.raises(ValueError, match="Invalid image dimensions"):
        epd.getbuffer(Image.new("RGB", (100, 100)))


def test_large_spi_write_uses_initialized_device(monkeypatch):
    writes = []

    class FakeSPI:
        def writebytes2(self, data):
            writes.append(data)

    monkeypatch.setattr(epdconfig, "_SPI", FakeSPI())
    epdconfig.spi_writebyte2([1, 2, 3])

    assert writes == [[1, 2, 3]]
