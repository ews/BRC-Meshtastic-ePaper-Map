"""WaveShare 7.3-inch E6/Spectra 6 e-paper driver.

Adapted from WaveShare's official ``epd7in3e.py`` at commit
7523aeaff09219e66478ef1603f0cc6618a48377. The panel accepts two packed
four-bit color indexes per byte.
"""

import logging

from PIL import Image

from . import epdconfig

EPD_WIDTH = 800
EPD_HEIGHT = 480

logger = logging.getLogger(__name__)


class EPD:
    """Driver for the 800x480 WaveShare 7.3-inch E6 full-color panel."""

    BLACK = 0x000000
    WHITE = 0xFFFFFF
    YELLOW = 0xFFFF00
    RED = 0xFF0000
    BLUE = 0x0000FF
    GREEN = 0x00FF00

    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT

    def reset(self):
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)

    def send_command(self, command):
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data2(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte2(data)
        epdconfig.digital_write(self.cs_pin, 1)

    def read_busy(self):
        logger.debug("e-paper busy")
        while epdconfig.digital_read(self.busy_pin) == 0:
            epdconfig.delay_ms(5)
        logger.debug("e-paper busy released")

    def turn_on_display(self):
        self.send_command(0x04)
        self.read_busy()
        self.send_command(0x12)
        self.send_data(0x00)
        self.read_busy()
        self.send_command(0x02)
        self.send_data(0x00)
        self.read_busy()

    def init(self):
        if epdconfig.module_init() != 0:
            return -1

        self.reset()
        self.read_busy()
        epdconfig.delay_ms(30)

        commands = (
            (0xAA, (0x49, 0x55, 0x20, 0x08, 0x09, 0x18)),
            (0x01, (0x3F,)),
            (0x00, (0x5F, 0x69)),
            (0x03, (0x00, 0x54, 0x00, 0x44)),
            (0x05, (0x40, 0x1F, 0x1F, 0x2C)),
            (0x06, (0x6F, 0x1F, 0x17, 0x49)),
            (0x08, (0x6F, 0x1F, 0x1F, 0x22)),
            (0x30, (0x03,)),
            (0x50, (0x3F,)),
            (0x60, (0x02, 0x00)),
            (0x61, (0x03, 0x20, 0x01, 0xE0)),
            (0x84, (0x01,)),
            (0xE3, (0x2F,)),
        )
        for command, data in commands:
            self.send_command(command)
            for value in data:
                self.send_data(value)

        self.send_command(0x04)
        self.read_busy()
        return 0

    def getbuffer(self, image):
        """Quantize an image to the E6 palette and pack two pixels per byte."""
        if image.size == (self.width, self.height):
            image_temp = image
        elif image.size == (self.height, self.width):
            image_temp = image.rotate(90, expand=True)
        else:
            raise ValueError(
                f"Invalid image dimensions {image.size}; expected "
                f"{(self.width, self.height)} or {(self.height, self.width)}"
            )

        palette = Image.new("P", (1, 1))
        palette.putpalette(
            (
                0, 0, 0,
                255, 255, 255,
                255, 255, 0,
                255, 0, 0,
                0, 0, 0,
                0, 0, 255,
                0, 255, 0,
            )
            + (0, 0, 0) * 249
        )
        indexed = image_temp.convert("RGB").quantize(palette=palette)
        pixels = indexed.tobytes("raw")

        return bytearray(
            (pixels[i] << 4) | pixels[i + 1]
            for i in range(0, len(pixels), 2)
        )

    def display(self, image):
        self.send_command(0x10)
        self.send_data2(image)
        self.turn_on_display()

    def clear(self, color=0x11):
        self.send_command(0x10)
        self.send_data2([color] * (self.width * self.height // 2))
        self.turn_on_display()

    Clear = clear

    def sleep(self):
        self.send_command(0x07)
        self.send_data(0xA5)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
