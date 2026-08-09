"""WaveShare ePaper configuration — SPI and GPIO initialization.

This is the standard hardware abstraction layer for WaveShare ePaper HATs.
Requires RPi.GPIO and spidev (Raspberry Pi only).
"""

import logging
import time

logger = logging.getLogger(__name__)

# Default pin configuration for WaveShare ePaper HAT
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24

_SPI = None


def module_init():
    """Initialize GPIO and SPI."""
    try:
        from RPi import GPIO
    except ImportError:
        logger.error("RPi.GPIO not available — not running on a Raspberry Pi?")
        return -1

    try:
        import spidev
    except ImportError:
        logger.error("spidev not available — enable SPI with raspi-config")
        return -1

    global _SPI
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(RST_PIN, GPIO.OUT)
    GPIO.setup(DC_PIN, GPIO.OUT)
    GPIO.setup(CS_PIN, GPIO.OUT)
    GPIO.setup(BUSY_PIN, GPIO.IN)

    _SPI = spidev.SpiDev()
    _SPI.open(0, 0)
    _SPI.max_speed_hz = 4000000
    _SPI.mode = 0b00

    return 0


def module_exit():
    """Clean up GPIO and SPI."""
    try:
        from RPi import GPIO
    except ImportError:
        return
    if _SPI is not None:
        _SPI.close()
    GPIO.cleanup()


def delay_ms(ms):
    """Delay in milliseconds."""
    time.sleep(ms / 1000.0)


def spi_writebyte(data):
    """Write a byte over SPI."""
    if _SPI is None:
        return
    _SPI.writebytes([data])


def digital_write(pin, value):
    """Set a GPIO pin high or low."""
    from RPi import GPIO

    GPIO.output(pin, value)


def digital_read(pin):
    """Read a GPIO pin."""
    from RPi import GPIO

    return GPIO.input(pin)
