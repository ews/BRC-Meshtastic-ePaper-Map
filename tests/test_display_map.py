"""Tests for display refresh decisions and E6 frame composition."""

from types import SimpleNamespace

import display_map
import pytest
from PIL import Image, ImageChops, ImageDraw
from renderer import assign_burner_emojis, draw_node_labels


def _node(lat=40.783247, lon=-119.207884):
    return {
        "node_id": "!1234",
        "coordinates": {"latitude": lat, "longitude": lon, "time": 0},
        "image_coordinates": (240, 516),
        "bm_coordinates": "12:00 + The Man",
    }


def test_unchanged_coordinates_do_not_request_refresh():
    burners = {"Alice": _node()}

    assert display_map.equal_bm_coordinates(burners, burners)


def test_new_node_requests_refresh():
    assert not display_map.equal_bm_coordinates({"Alice": _node()}, {})


def test_changed_emoji_requests_refresh_without_movement():
    old = {"Alice": {**_node(), "emoji": "♥"}}
    new = {"Alice": {**_node(), "emoji": "★"}}

    assert not display_map.equal_bm_coordinates(new, old)


def test_burners_get_stable_distinct_emojis():
    burners = {
        "Alice": _node(),
        "Bob": {**_node(), "node_id": "!5678"},
    }
    assign_burner_emojis(burners)
    first = {name: data["emoji"] for name, data in burners.items()}

    assign_burner_emojis(burners)

    assert len(set(first.values())) == 2
    assert {name: data["emoji"] for name, data in burners.items()} == first


def test_emoji_labels_render_on_list_and_map():
    burners = {"Alice": _node()}
    frame = Image.new("RGB", (480, 800), "white")
    blank = frame.copy()

    draw_node_labels(burners, ImageDraw.Draw(frame))

    assert burners["Alice"]["emoji"]
    assert ImageChops.difference(frame, blank).getbbox() is not None


def test_friend_filter_merges_persistent_emoji():
    class Store:
        def get_friends(self):
            return [{"node_id": "!1234", "emoji": "♥"}]

    filtered, _ = display_map._filter_friend_burners(
        {"Alice": _node(), "Unknown": {**_node(), "node_id": "!9999"}}, Store()
    )

    assert list(filtered) == ["Alice"]
    assert filtered["Alice"]["emoji"] == "♥"


def test_map_frame_is_rgb_and_has_supported_dimensions():
    base = display_map._load_map()
    frame, _ = display_map._new_frame(base)

    assert frame.mode == "RGB"
    assert frame.size == (480, 800)


def test_initial_map_is_displayed_before_mesh_connection(monkeypatch):
    events = []

    class FakeEPD:
        def getbuffer(self, frame):
            return frame

        def display(self, frame):
            events.append("display")

        def sleep(self):
            events.append("sleep")

    def stop_at_mesh_connection():
        events.append("connect")
        raise RuntimeError("stop test after startup")

    monkeypatch.setattr(display_map, "_init_epd", FakeEPD)
    monkeypatch.setattr(display_map, "connect_mesh_serial", stop_at_mesh_connection)
    args = SimpleNamespace(no_friends=True, screen=False, debug=False)

    with pytest.raises(RuntimeError, match="stop test"):
        display_map.main(args)

    assert events == ["display", "connect", "sleep"]
