"""Meshtastic radio interface — connection, polling, and node data extraction."""

import time
import threading
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


class ChannelPositionCache:
    """Keep the latest positions received on one Meshtastic channel."""

    def __init__(self, channel_index):
        self.channel_index = int(channel_index)
        self._positions = {}
        self._logged_other_channels = set()
        self._lock = threading.Lock()

    def receive(self, packet, interface=None):
        """Record a decoded position packet when it belongs to this channel."""
        try:
            packet_channel = int(packet.get("channel", 0))
        except (TypeError, ValueError):
            logging.warning(
                "ignoring position with invalid channel %r", packet.get("channel")
            )
            return
        if packet_channel != self.channel_index:
            with self._lock:
                first_on_channel = packet_channel not in self._logged_other_channels
                self._logged_other_channels.add(packet_channel)
            if first_on_channel:
                logging.info(
                    "ignoring positions on channel %d; tracking channel %d",
                    packet_channel,
                    self.channel_index,
                )
            return

        position = _normalized_position(packet.get("decoded", {}).get("position", {}))
        if position is None:
            logging.info(
                "ignoring channel %d position without latitude/longitude",
                self.channel_index,
            )
            return

        node_id = _packet_node_id(packet)
        if not node_id:
            logging.info("ignoring channel %d position without sender", self.channel_index)
            return

        with self._lock:
            self._positions[node_id] = position
        logging.info("received channel %d position from %s", self.channel_index, node_id)

    def snapshot(self, interface=None):
        """Return NodeDB-shaped records for conversion and rendering."""
        with self._lock:
            positions = {
                node_id: dict(position)
                for node_id, position in self._positions.items()
            }

        nodes = getattr(interface, "nodes", {}) or {}
        records = []
        for node_id, position in positions.items():
            user = dict(nodes.get(node_id, {}).get("user", {}))
            user.setdefault("id", node_id)
            user.setdefault("longName", user.get("shortName") or node_id)
            records.append((node_id, {"user": user, "position": position}))
        return records

    def count(self):
        """Return the number of senders with a cached channel position."""
        with self._lock:
            return len(self._positions)


def time_from_timestamp(timestamp):
    """Format a Unix timestamp as HH:MM:SS."""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def connect_serial():
    """Connect over serial, falling back to TCP localhost when none is found."""
    delay = _RETRY_BASE_SEC
    while True:
        try:
            logging.info("connecting to Meshtastic over serial...")
            iface = meshtastic.serial_interface.SerialInterface()
            # Some Meshtastic releases print that they are attempting TCP when
            # no serial port exists, but return an uninitialized SerialInterface
            # instead. Detect that object and perform the fallback ourselves.
            if not hasattr(iface, "nodes"):
                logging.info("no serial radio found; trying TCP at localhost")
                iface = meshtastic.tcp_interface.TCPInterface("localhost")
            if not hasattr(iface, "nodes"):
                raise ConnectionError("Meshtastic interface has no node database")
            logging.info("connected")
            return iface
        except Exception as e:
            logging.warning("mesh connection failed: %s — retrying in %ds", e, delay)
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
            logging.warning("mesh poll failed: %s — retrying in %ds", e, delay)
            time.sleep(delay)
            delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_SEC)


def add_bm_coordinates(burners):
    """Convert raw Meshtastic node data to burner dicts with BRC addresses.

    Returns a dict keyed by username with 'coordinates', 'bm_coordinates',
    and 'image_coordinates' for each node that has a GPS position.
    """
    output = {}
    for node_id, data in burners:
        logging.debug("processing node %s", node_id)
        logging.debug("%s", data)
        user = data.get("user", {})
        username = user.get("longName") or user.get("shortName") or node_id
        coordinates = _normalized_position(
            data.get("position", data.get("coordinates", {}))
        )

        if coordinates is not None:
            output[username] = {}
            output[username]["node_id"] = node_id
            output[username]["coordinates"] = coordinates

            lat = output[username]["coordinates"]["latitude"]
            lon = output[username]["coordinates"]["longitude"]

            output[username]["bm_coordinates"] = gps_to_burning_man(lat, lon)
            output[username]["image_coordinates"] = gps_to_image_coordinates(
                (lat, lon, username)
            )
            logging.debug("image coordinates %s", output[username]["image_coordinates"])
        else:
            logging.info("no position for %s (%s)", username, node_id)

    return output


def _normalized_position(position):
    """Return a position with decimal latitude/longitude, or None."""
    if not isinstance(position, dict):
        return None
    normalized = {key: value for key, value in position.items() if key != "raw"}
    if "latitude" not in normalized and "latitudeI" in normalized:
        normalized["latitude"] = normalized["latitudeI"] * 1e-7
    if "longitude" not in normalized and "longitudeI" in normalized:
        normalized["longitude"] = normalized["longitudeI"] * 1e-7
    if normalized.get("latitude") is None or normalized.get("longitude") is None:
        return None
    normalized.setdefault("time", 0)
    return normalized


def _packet_node_id(packet):
    """Return a Meshtastic !hex node ID from a decoded packet."""
    if packet.get("fromId"):
        return str(packet["fromId"])
    if packet.get("from") is None:
        return None
    try:
        return f"!{int(packet['from']):08x}"
    except (TypeError, ValueError):
        return str(packet["from"])
