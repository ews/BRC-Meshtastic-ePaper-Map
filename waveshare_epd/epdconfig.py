"""WaveShare ePaper configuration — SPI and GPIO initialization.

This is the standard hardware abstraction layer for WaveShare ePaper HATs.
Requires RPi.GPIO and spidev (Raspberry Pi only).
"""
# ruff: noqa

import logging
import time

logger = logging.getLogger(__name__)

# Default pin configuration for WaveShare ePaper HAT
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24
PWR_PIN = 27

_SPI = None


def module_init():
    """Initialize GPIO and SPI."""
    try:
        import RPi.GPIO as GPIO
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
    GPIO.setup(PWR_PIN, GPIO.OUT)
    GPIO.output(PWR_PIN, GPIO.HIGH)

    _SPI = spidev.SpiDev()
    _SPI.open(0, 0)
    _SPI.max_speed_hz = 4000000
    _SPI.mode = 0b00

    return 0


def module_exit():
    """Clean up GPIO and SPI."""
    try:
        import RPi.GPIO as GPIO

        GPIO.output(PWR_PIN, GPIO.LOW)
        GPIO.cleanup()
    except ImportError:
        pass
    if _SPI is not None:
        _SPI.close()


def delay_ms(ms):
    """Delay in milliseconds."""
    time.sleep(ms / 1000.0)


def spi_writebyte(data):
    """Write bytes over SPI."""
    if _SPI is None:
        return
    _SPI.writebytes(data)


def spi_writebyte2(data):
    """Write a framebuffer, allowing spidev to split large transfers."""
    if _SPI is None:
        raise RuntimeError("SPI is not initialized")
    _SPI.writebytes2(data)


def digital_write(pin, value):
    """Set a GPIO pin high or low."""
    import RPi.GPIO as GPIO

    GPIO.output(pin, value)


def digital_read(pin):
    """Read a GPIO pin."""
    import RPi.GPIO as GPIO

    return GPIO.input(pin)
