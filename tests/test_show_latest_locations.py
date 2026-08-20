"""Tests for the latest map-location comparison table."""

from history_store import HistoryStore
from tools.show_latest_locations import latest_location_rows, render_latest_locations


def _burner(latitude, source_time):
    return {
        "Alice": {
            "node_id": "!abcd1234",
            "coordinates": {
                "latitude": latitude,
                "longitude": -119.207884,
                "altitude": 3904,
                "time": source_time,
            },
            "bm_coordinates": "12:00+The Man",
        }
    }


def test_latest_location_table_shows_only_position_used_after_restart(tmp_path):
    database = tmp_path / "history.sqlite3"
    store = HistoryStore(database)
    store.record_positions(_burner(40.780000, 100))
    store.record_positions(_burner(40.790000, 200))
    store.close()

    rows = latest_location_rows(database)
    table = render_latest_locations(database)

    assert len(rows) == 1
    assert rows[0][0:4] == ["Alice", "!abcd1234", "40.790000", "-119.207884"]
    assert rows[0][4:6] == [3904, "12:00+The Man"]
    assert "Alice" in table
    assert "40.790000" in table
    assert "40.780000" not in table
