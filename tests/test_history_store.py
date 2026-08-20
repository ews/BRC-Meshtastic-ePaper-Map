"""Tests for SQLite position and chat history."""

import sqlite3
from types import SimpleNamespace

from history_store import HistoryStore, sender_name_for_packet


def _burner(source_time=100):
    return {
        "Alice": {
            "node_id": "!abcd1234",
            "coordinates": {
                "latitude": 40.783247,
                "longitude": -119.207884,
                "altitude": 3904,
                "time": source_time,
            },
            "bm_coordinates": "12:00+The Man",
        }
    }


def test_positions_are_persisted_and_duplicate_reports_are_ignored(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)

    assert store.record_positions(_burner()) == 1
    assert store.record_positions(_burner()) == 0
    assert store.record_positions(_burner(source_time=101)) == 1
    store.close()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT node_id, name, latitude, longitude, brc_address "
            "FROM positions ORDER BY source_time"
        ).fetchall()
    assert rows == [
        ("!abcd1234", "Alice", 40.783247, -119.207884, "12:00+The Man"),
        ("!abcd1234", "Alice", 40.783247, -119.207884, "12:00+The Man"),
    ]


def test_latest_positions_returns_newest_location_for_every_node(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    assert store.record_positions(_burner(source_time=100)) == 1
    moved = _burner(source_time=200)
    moved["Alice"]["coordinates"]["latitude"] = 40.79
    assert store.record_positions(moved) == 1
    bob = {
        "Bob": {
            "node_id": "!bbbb1234",
            "coordinates": {
                "latitude": 40.78,
                "longitude": -119.20,
                "time": 150,
            },
            "bm_coordinates": "03:00+B",
        }
    }
    assert store.record_positions(bob) == 1

    records = dict(store.latest_positions())
    store.close()

    assert set(records) == {"!abcd1234", "!bbbb1234"}
    assert records["!abcd1234"]["user"]["longName"] == "Alice"
    assert records["!abcd1234"]["position"]["latitude"] == 40.79
    assert records["!abcd1234"]["position"]["time"] == 200
    assert records["!bbbb1234"]["user"]["longName"] == "Bob"


def test_received_chat_is_persisted_once(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    packet = {
        "id": 42,
        "fromId": "!abcd1234",
        "toId": "^all",
        "rxTime": 1234,
        "channel": 2,
        "decoded": {"text": "Meet at the Man"},
    }

    assert store.record_message(packet, "Alice")
    assert not store.record_message(packet, "Alice")
    store.close()

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT packet_id, sender_id, sender_name, recipient_id, channel, text "
            "FROM messages"
        ).fetchone()
    assert row == ("42", "!abcd1234", "Alice", "^all", 2, "Meet at the Man")


def test_sender_name_comes_from_mesh_node_database():
    interface = SimpleNamespace(nodes={"!abcd1234": {"user": {"longName": "Alice"}}})
    assert sender_name_for_packet({"fromId": "!abcd1234"}, interface) == "Alice"
