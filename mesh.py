"""Meshtastic radio interface — connection, polling, and node data extraction."""

import time
from datetime import datetime

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface

import config as c
from coordinates import gps_to_burning_man, gps_to_image_coordinates

logging = c.logging

# Retry settings for mesh connection
_RETRY_BASE_SEC = 5
_RETRY_MAX_SEC = 120
_RETRY_FACTOR = 2


def time_from_timestamp(timestamp):
    """Format a Unix timestamp as HH:MM:SS."""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def connect_serial():
    """Connect to Meshtastic over serial with exponential backoff retry."""
    delay = _RETRY_BASE_SEC
    while True:
        try:
            logging.info("connecting to Meshtastic over serial...")
            iface = meshtastic.serial_interface.SerialInterface()
            logging.info("connected")
            return iface
        except Exception as e:
            logging.warning(
                "mesh connection failed: %s — retrying in %ds", e, delay
            )
            time.sleep(delay)
            delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_SEC)


def connect_tcp(host):
    """Connect to Meshtastic over TCP with exponential backoff retry."""
    delay = _RETRY_BASE_SEC
    while True:
        try:
            logging.info("connecting to Meshtastic at %s...", host)
            iface = meshtastic.tcp_interface.TCPInterface(host)
            logging.info("connected")
            return iface
        except Exception as e:
            logging.warning(
                "mesh connection to %s failed: %s — retrying in %ds",
                host,
                e,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_SEC)


def get_mesh_info(interface):
    """Poll mesh nodes with retry on transient failures."""
    delay = _RETRY_BASE_SEC
    while True:
        try:
            return interface.nodes.items()
        except Exception as e:
            logging.warning(
                "mesh poll failed: %s — retrying in %ds", e, delay
            )
            time.sleep(delay)
            delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_SEC)


def add_bm_coordinates(burners):
    """Convert raw Meshtastic node data to burner dicts with BRC addresses.

    Returns a dict keyed by username with 'coordinates', 'bm_coordinates',
    and 'image_coordinates' for each node that has a GPS position.
    """
    output = {}
    for _nodename, data in burners:
        logging.debug("processing node %s", _nodename)
        logging.debug("%s", data)
        username = data["user"]["longName"]

        if "coordinates" in data and "latitude" in data["coordinates"]:
            output[username] = {}
            output[username]["coordinates"] = data["coordinates"]

            lat = output[username]["coordinates"]["latitude"]
            lon = output[username]["coordinates"]["longitude"]

            output[username]["bm_coordinates"] = gps_to_burning_man(lat, lon)
            output[username]["image_coordinates"] = gps_to_image_coordinates(
                (lat, lon, username)
            )
            logging.debug(
                "image coordinates %s", output[username]["image_coordinates"]
            )
        else:
            logging.info("no position for %s %s", username, data)

    return output
