"""Tests for CSV history exports."""

import csv

from history_store import HistoryStore
from tools.export_history import export_history


def test_position_and_conversation_exports(tmp_path):
    database = tmp_path / "history.sqlite3"
    store = HistoryStore(database)
    store.record_positions(
        {
            "Alice": {
                "node_id": "!abcd1234",
                "coordinates": {
                    "latitude": 40.783247,
                    "longitude": -119.207884,
                    "time": 100,
                },
                "bm_coordinates": "12:00 + The Man",
            }
        }
    )
    store.record_message(
        {
            "id": 42,
            "fromId": "!abcd1234",
            "toId": "^all",
            "rxTime": 101,
            "decoded": {"text": "Meet at the Man"},
        },
        "Alice",
    )
    store.close()

    positions = tmp_path / "exports" / "positions.csv"
    conversations = tmp_path / "exports" / "conversations.csv"
    assert export_history("positions", database, positions) == 1
    assert export_history("conversations", database, conversations) == 1

    with positions.open(newline="", encoding="utf-8") as source:
        position_rows = list(csv.DictReader(source))
    with conversations.open(newline="", encoding="utf-8") as source:
        conversation_rows = list(csv.DictReader(source))

    assert position_rows[0]["name"] == "Alice"
    assert position_rows[0]["brc_address"] == "12:00 + The Man"
    assert conversation_rows[0]["sender_name"] == "Alice"
    assert conversation_rows[0]["text"] == "Meet at the Man"
