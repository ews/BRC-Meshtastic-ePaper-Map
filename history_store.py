"""Thread-safe SQLite history for Meshtastic positions and chat messages."""

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


class HistoryStore:
    """Persist mesh history without rewriting the friend allowlist."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    source_time INTEGER NOT NULL,
                    node_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    altitude INTEGER,
                    brc_address TEXT NOT NULL,
                    UNIQUE(node_id, source_time, latitude, longitude)
                );
                CREATE INDEX IF NOT EXISTS positions_node_time
                    ON positions(node_id, source_time);

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    packet_id TEXT NOT NULL UNIQUE,
                    rx_time INTEGER,
                    sender_id TEXT,
                    sender_name TEXT,
                    recipient_id TEXT,
                    channel INTEGER,
                    text TEXT NOT NULL,
                    via_mqtt INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS messages_sender_time
                    ON messages(sender_id, rx_time);
                """
            )

    def record_positions(self, burners: dict) -> int:
        """Insert new position reports and return the number added."""
        observed_at = _now_iso()
        rows = []
        for name, data in burners.items():
            coordinates = data.get("coordinates", {})
            lat = coordinates.get("latitude")
            lon = coordinates.get("longitude")
            if lat is None or lon is None:
                continue
            rows.append(
                (
                    observed_at,
                    _integer(coordinates.get("time"), default=0),
                    data.get("node_id", ""),
                    name,
                    float(lat),
                    float(lon),
                    _integer(coordinates.get("altitude")),
                    data.get("bm_coordinates", ""),
                )
            )

        if not rows:
            return 0
        with self._lock, self._connection:
            before = self._connection.total_changes
            self._connection.executemany(
                """
                INSERT OR IGNORE INTO positions (
                    observed_at, source_time, node_id, name, latitude,
                    longitude, altitude, brc_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return self._connection.total_changes - before

    def record_message(self, packet: dict, sender_name: str | None = None) -> bool:
        """Insert one received text packet; duplicate packet IDs are ignored."""
        decoded = packet.get("decoded", {})
        text = decoded.get("text")
        if not isinstance(text, str) or not text:
            return False

        packet_id = packet.get("id")
        if packet_id is None:
            identity = json.dumps(
                {
                    "from": packet.get("fromId", packet.get("from")),
                    "to": packet.get("toId", packet.get("to")),
                    "rxTime": packet.get("rxTime"),
                    "channel": packet.get("channel", 0),
                    "text": text,
                },
                sort_keys=True,
            ).encode()
            packet_id = hashlib.sha256(identity).hexdigest()

        row = (
            _now_iso(),
            str(packet_id),
            _integer(packet.get("rxTime")),
            _node_id(packet, "fromId", "from"),
            sender_name,
            _node_id(packet, "toId", "to"),
            _integer(packet.get("channel"), default=0),
            text,
            int(bool(packet.get("viaMqtt", False))),
        )
        with self._lock, self._connection:
            before = self._connection.total_changes
            self._connection.execute(
                """
                INSERT OR IGNORE INTO messages (
                    received_at, packet_id, rx_time, sender_id, sender_name,
                    recipient_id, channel, text, via_mqtt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            return self._connection.total_changes > before

    def close(self) -> None:
        """Flush and close the database."""
        with self._lock:
            self._connection.close()


def sender_name_for_packet(packet: dict, interface) -> str | None:
    """Resolve a packet sender to the current Meshtastic long name."""
    sender_id = _node_id(packet, "fromId", "from")
    if not sender_id or interface is None:
        return None
    node = getattr(interface, "nodes", {}).get(sender_id, {})
    user = node.get("user", {})
    return user.get("longName") or user.get("shortName")


def _node_id(packet: dict, id_key: str, number_key: str) -> str | None:
    value = packet.get(id_key)
    if value:
        return str(value)
    number = packet.get(number_key)
    if number is None:
        return None
    try:
        return f"!{int(number):08x}"
    except (TypeError, ValueError):
        return str(number)


def _integer(value, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
