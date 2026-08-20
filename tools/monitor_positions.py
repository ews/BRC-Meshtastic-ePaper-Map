#!/usr/bin/env python3
"""Monitor the mesh and log every shared position with its channel.

Only logs location packets: channel, sender, and coordinates. Nothing else.

Usage:
    python tools/monitor_positions.py                  # serial, auto-detect
    python tools/monitor_positions.py --port /dev/ttyACM0
    python tools/monitor_positions.py --host 192.168.0.188
    python tools/monitor_positions.py --ble "TRACKER L1"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import meshtastic
import meshtastic.ble_interface
import meshtastic.serial_interface
import meshtastic.tcp_interface
from pubsub import pub

# ── logging: only position lines are shown ─────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("position-monitor")

_RETRY_BASE_SEC = 5
_RETRY_MAX_SEC = 120
_RETRY_FACTOR = 2


def connect(args):
    """Connect to a radio, retrying with backoff."""
    delay = _RETRY_BASE_SEC
    while True:
        try:
            if args.ble:
                log.info("connecting over BLE (--ble %s)...", args.ble or "auto")
                iface = meshtastic.ble_interface.BLEInterface(
                    args.ble if args.ble else None
                )
            elif args.host:
                log.info("connecting over TCP to %s...", args.host)
                iface = meshtastic.tcp_interface.TCPInterface(args.host)
            else:
                log.info("connecting over serial...")
                iface = meshtastic.serial_interface.SerialInterface(
                    devPath=args.port or None
                )
                if not hasattr(iface, "nodes"):
                    log.info("no serial radio found; trying TCP at localhost")
                    iface = meshtastic.tcp_interface.TCPInterface("localhost")
            if not hasattr(iface, "nodes"):
                raise ConnectionError("interface has no node database")
            log.info("connected; listening for position packets")
            return iface
        except Exception as e:  # noqa: BLE001 - retry any connection failure
            log.warning("connection failed: %s — retrying in %ds", e, delay)
            time.sleep(delay)
            delay = min(delay * _RETRY_FACTOR, _RETRY_MAX_SEC)


def packet_channel(packet) -> int:
    """Return the raw channel number from a packet."""
    try:
        return int(packet.get("channel", 0))
    except (TypeError, ValueError):
        return -1


def packet_node_id(packet):
    """Return the sender's !hex node ID, or None."""
    if packet.get("fromId"):
        return str(packet["fromId"])
    if packet.get("from") is None:
        return None
    try:
        return f"!{int(packet['from']):08x}"
    except (TypeError, ValueError):
        return str(packet["from"])


def normalize_position(position) -> dict | None:
    """Return decimal lat/lon from a decoded position dict, or None."""
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


def node_name(interface, node_id) -> str:
    """Return a human-readable sender name from the NodeDB."""
    nodes = getattr(interface, "nodes", {}) or {}
    user = nodes.get(node_id, {}).get("user", {}) if node_id else {}
    return (
        user.get("longName")
        or user.get("shortName")
        or node_id
        or "unknown"
    )


def on_position(packet, interface=None, **kwargs):
    """Log every received position with its channel and coordinates."""
    channel = packet_channel(packet)
    node_id = packet_node_id(packet)
    name = node_name(interface, node_id)
    position = normalize_position(packet.get("decoded", {}).get("position", {}))
    if position is None:
        log.info(
            "POSITION channel=%d sender=%s node_id=%s — no latitude/longitude",
            channel,
            name,
            node_id,
        )
        return
    log.info(
        "POSITION channel=%d sender=%s node_id=%s latitude=%.6f longitude=%.6f",
        channel,
        name,
        node_id,
        position["latitude"],
        position["longitude"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial device, e.g. /dev/ttyACM0")
    parser.add_argument("--host", help="TCP host, e.g. 192.168.0.188")
    parser.add_argument(
        "--ble",
        nargs="?",
        const="",
        default=None,
        help="connect over BLE, optionally with a device name",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interface = None

    try:
        interface = connect(args)
        pub.subscribe(on_position, "meshtastic.receive.position")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("monitor stopped")
        return 0
    finally:
        try:
            if interface is not None:
                interface.close()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup on exit
            log.warning("interface close failed: %s", e)


if __name__ == "__main__":
    raise SystemExit(main())
