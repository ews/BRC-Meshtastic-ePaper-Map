#!/usr/bin/env python3
"""Show the last-known SQLite positions currently restored by the map."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from tabulate import tabulate

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as c

LATEST_POSITIONS_QUERY = """
    SELECT p.name, p.node_id, p.latitude, p.longitude, p.altitude,
           p.brc_address, p.source_time
    FROM positions AS p
    JOIN (
        SELECT node_id, MAX(id) AS latest_id
        FROM positions
        GROUP BY node_id
    ) AS latest ON latest.latest_id = p.id
    ORDER BY p.name COLLATE NOCASE, p.node_id
"""


def _position_time(timestamp: int) -> str:
    """Format a Meshtastic timestamp in local 12-hour time."""
    if not timestamp:
        return "N/A"
    value = datetime.fromtimestamp(timestamp, timezone.utc).astimezone()
    hour = value.hour % 12 or 12
    period = "AM" if value.hour < 12 else "PM"
    return f"{value:%Y-%m-%d} {hour}:{value.minute:02d} {period}"


def latest_location_rows(database: str | Path) -> list[list[object]]:
    """Return display-ready rows for each node's newest SQLite position."""
    database = Path(database)
    if not database.exists():
        raise FileNotFoundError(
            f"History database not found: {database}. Run 'make run-map' first."
        )

    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(LATEST_POSITIONS_QUERY).fetchall()
    finally:
        connection.close()

    return [
        [
            name,
            node_id,
            f"{latitude:.6f}",
            f"{longitude:.6f}",
            altitude if altitude is not None else "N/A",
            brc_address,
            _position_time(source_time),
        ]
        for name, node_id, latitude, longitude, altitude, brc_address, source_time in rows
    ]


def render_latest_locations(database: str | Path) -> str:
    """Render the map's retained last-known locations as a table."""
    rows = latest_location_rows(database)
    if not rows:
        return "No positions are stored in the map history."
    return tabulate(
        rows,
        headers=("User", "ID", "Latitude", "Longitude", "Altitude", "BRC", "Shared"),
        tablefmt="fancy_grid",
        disable_numparse=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=c.history_database)
    args = parser.parse_args()

    try:
        table = render_latest_locations(args.database)
    except (FileNotFoundError, sqlite3.Error) as error:
        parser.exit(1, f"error: {error}\n")
    print("Map SQLite last-known locations (persisted independently of radio NodeDB):")
    print(table)


if __name__ == "__main__":
    main()
