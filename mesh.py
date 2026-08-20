"""Meshtastic radio interface — connection, polling, and node data extraction."""

import threading
import time
from datetime import datetime, timezone

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface

import config as c
from coordinates import (
    gps_to_burning_man,
    gps_to_image_coordinates,
    warn_if_far_from_brc,
)

logging = c.logging

# Retry settings for mesh connection
_RETRY_BASE_SEC = 5
_RETRY_MAX_SEC = 120
_RETRY_FACTOR = 2
_last_warned_far_positions = {}
_warned_far_positions_lock = threading.Lock()


class ChannelPositionCache:
    """Keep the latest positions received on one Meshtastic channel."""

    def __init__(self, channel_index):
        self.channel_index = int(channel_index)
        self._positions = {}
        self._users = {}
        self._logged_other_channel_nodes = set()
        self._lock = threading.Lock()

    def receive(self, packet, interface=None):
        """Record a decoded position packet when it belongs to this channel."""
        node_id = _packet_node_id(packet)
        user = _node_user(interface, node_id)
        identity = _node_identity(node_id, user)
        try:
            packet_channel = int(packet.get("channel", 0))
        except (TypeError, ValueError):
            logging.warning(
                "ignoring position with invalid channel %r", packet.get("channel")
            )
            return
        if packet_channel != self.channel_index:
            sender_key = (packet_channel, node_id or "unknown")
            with self._lock:
                first_from_sender = (
                    sender_key not in self._logged_other_channel_nodes
                )
                self._logged_other_channel_nodes.add(sender_key)
            if first_from_sender:
                logging.info(
                    "ignoring channel %d position from %s; tracking channel %d",
                    packet_channel,
                    identity,
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

        if not node_id:
            logging.info(
                "ignoring channel %d position without sender", self.channel_index
            )
            return

        with self._lock:
            changed = self._positions.get(node_id) != position
            self._positions[node_id] = position
            if user:
                self._users[node_id] = user
        log = logging.info if changed else logging.debug
        log(
            "received channel %d position from %s latitude=%.6f longitude=%.6f",
            self.channel_index,
            identity,
            position["latitude"],
            position["longitude"],
        )

    def restore(self, records):
        """Merge NodeDB-shaped last-known positions into the cache.

        Newer source timestamps win. This accepts both records reconstructed
        from SQLite and ``interface.nodes.items()`` from the radio.
        """
        restored = 0
        for node_id, data in records:
            position = _normalized_position(
                data.get("position", data.get("coordinates", {}))
            )
            if position is None:
                continue
            node_id = str(node_id)
            user = dict(data.get("user", {}))
            user.setdefault("id", node_id)

            with self._lock:
                existing = self._positions.get(node_id)
                if existing is not None and _position_time(existing) > _position_time(
                    position
                ):
                    continue
                changed = existing != position
                self._positions[node_id] = position
                if user:
                    self._users[node_id] = user
                if changed:
                    restored += 1
        return restored

    def snapshot(self, interface=None):
        """Return NodeDB-shaped records for conversion and rendering."""
        with self._lock:
            positions = {
                node_id: dict(position) for node_id, position in self._positions.items()
            }
            stored_users = {
                node_id: dict(user) for node_id, user in self._users.items()
            }

        nodes = getattr(interface, "nodes", {}) or {}
        records = []
        for node_id, position in positions.items():
            user = stored_users.get(node_id, {})
            user.update(nodes.get(node_id, {}).get("user", {}))
            user.setdefault("id", node_id)
            user.setdefault("longName", user.get("shortName") or node_id)
            records.append((node_id, {"user": user, "position": position}))
        return records

    def web_nodes(self, interface=None):
        """Return JSON-ready retained nodes for the emoji web app."""
        nodes = []
        for node_id, data in self.snapshot(interface):
            position = data["position"]
            user = data["user"]
            nodes.append(
                {
                    "node_id": node_id,
                    "name": user.get("longName") or user.get("shortName") or node_id,
                    "short_name": user.get("shortName", ""),
                    "brc_address": gps_to_burning_man(
                        position["latitude"],
                        position["longitude"],
                        validate=False,
                    ),
                    "position_time": position.get("time", 0),
                }
            )
        return nodes

    def count(self):
        """Return the number of senders with a retained position."""
        with self._lock:
            return len(self._positions)


def time_from_timestamp(timestamp):
    """Format a Unix timestamp as h:mm:ss AM/PM."""
    local_time = datetime.fromtimestamp(timestamp, timezone.utc).astimezone()
    hour = local_time.hour % 12 or 12
    period = "AM" if local_time.hour < 12 else "PM"
    return f"{hour}:{local_time.minute:02d}:{local_time.second:02d} {period}"


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
        identity = _node_identity(node_id, user)
        coordinates = _normalized_position(
            data.get("position", data.get("coordinates", {}))
        )

        if coordinates is not None:
            output[username] = {}
            output[username]["node_id"] = node_id
            output[username]["coordinates"] = coordinates

            lat = output[username]["coordinates"]["latitude"]
            lon = output[username]["coordinates"]["longitude"]

            _warn_far_position_once(node_id, lat, lon, identity)
            output[username]["bm_coordinates"] = gps_to_burning_man(
                lat,
                lon,
                validate=False,
            )
            output[username]["image_coordinates"] = gps_to_image_coordinates(
                (lat, lon, username),
                validate=False,
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


def _position_time(position):
    """Return a comparable Meshtastic source timestamp."""
    try:
        return int(position.get("time", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _node_user(interface, node_id):
    """Return current NodeDB user metadata for a packet sender."""
    if interface is None or not node_id:
        return {}
    nodes = getattr(interface, "nodes", {}) or {}
    return dict(nodes.get(node_id, {}).get("user", {}))


def _node_identity(node_id, user=None):
    """Return a stable, log-friendly node identity including hardware type."""
    user = user or {}
    resolved_id = node_id or user.get("id") or "unknown"
    name = user.get("longName") or user.get("shortName") or "unknown"
    short_name = user.get("shortName") or "unknown"
    hardware = user.get("hwModel") or "unknown"
    return (
        f"node_id={resolved_id} name={name!r} short={short_name!r} "
        f"hardware={hardware}"
    )


def _warn_far_position_once(node_id, latitude, longitude, identity):
    """Warn once while a node's far-away position remains unchanged."""
    key = node_id or identity
    position = (float(latitude), float(longitude), identity)
    with _warned_far_positions_lock:
        if _last_warned_far_positions.get(key) == position:
            return
        _last_warned_far_positions[key] = position
    warn_if_far_from_brc(latitude, longitude, subject=identity)
