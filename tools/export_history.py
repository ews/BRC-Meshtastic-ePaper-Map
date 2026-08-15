#!/usr/bin/env python3
"""Export SQLite mesh history to portable CSV files."""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as c

EXPORTS = {
    "positions": (
        """
        SELECT observed_at, source_time, node_id, name, latitude, longitude,
               altitude, brc_address
        FROM positions
        ORDER BY source_time, id
        """,
        (
            "observed_at",
            "source_time",
            "node_id",
            "name",
            "latitude",
            "longitude",
            "altitude",
            "brc_address",
        ),
    ),
    "conversations": (
        """
        SELECT received_at, packet_id, rx_time, sender_id, sender_name,
               recipient_id, channel, text, via_mqtt
        FROM messages
        ORDER BY COALESCE(rx_time, 0), id
        """,
        (
            "received_at",
            "packet_id",
            "rx_time",
            "sender_id",
            "sender_name",
            "recipient_id",
            "channel",
            "text",
            "via_mqtt",
        ),
    ),
}


def export_history(kind: str, database: str | Path, output: str | Path) -> int:
    """Export one history table to CSV and return its record count."""
    database = Path(database)
    output = Path(output)
    if not database.exists():
        raise FileNotFoundError(
            f"History database not found: {database}. Run 'make run-map' first."
        )

    query, columns = EXPORTS[kind]
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(query)
        with output.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.writer(destination)
            writer.writerow(columns)
            count = 0
            for row in rows:
                writer.writerow(row)
                count += 1
    finally:
        connection.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=EXPORTS)
    parser.add_argument("--database", default=c.history_database)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        count = export_history(args.kind, args.database, args.output)
    except (FileNotFoundError, sqlite3.Error) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Exported {count} {args.kind} records to {args.output}")


if __name__ == "__main__":
    main()
