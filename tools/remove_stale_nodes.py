#!/usr/bin/env python3
"""Remove nodes whose last-heard timestamp is older than a given age."""

from __future__ import annotations

import argparse
import time

import meshtastic.serial_interface


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial device, e.g. /dev/ttyACM0")
    parser.add_argument(
        "--max-age",
        type=int,
        default=86400,
        help="remove nodes not heard within this many seconds (default: 86400)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_age <= 0:
        raise SystemExit("--max-age must be positive")

    interface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
    try:
        cutoff = time.time() - args.max_age
        local_num = getattr(getattr(interface, "localNode", None), "nodeNum", None)
        stale = []
        for node_num, node in (getattr(interface, "nodesByNum", {}) or {}).items():
            if node_num == local_num:
                continue
            last_heard = node.get("lastHeard")
            if last_heard is not None and last_heard < cutoff:
                stale.append((node_num, node.get("user", {}).get("longName", "")))

        for node_num, name in stale:
            node_id = f"!{node_num:08x}"
            print(f"Removing {node_id}{f' ({name})' if name else ''}")
            interface.localNode.removeNode(node_num)
        print(f"Removed {len(stale)} stale node(s).")
    finally:
        interface.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
