"""Tests for display refresh decisions and E6 frame composition."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops, ImageDraw

import display_map
from renderer import (
    _clock_time,
    _detail_text,
    assign_burner_emojis,
    draw_chat_messages,
    draw_node_labels,
)


def _node(lat=40.783247, lon=-119.207884):
    return {
        "node_id": "!1234",
        "coordinates": {"latitude": lat, "longitude": lon, "time": 0},
        "image_coordinates": (240, 516),
        "bm_coordinates": "12:00+The Man",
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


def test_custom_emoji_is_reserved_before_automatic_assignment():
    from burner_emojis import default_emoji

    reserved = default_emoji("!1111")
    burners = {
        "Automatic": {**_node(), "node_id": "!1111"},
        "Custom": {**_node(), "node_id": "!9999", "emoji": reserved},
    }

    assign_burner_emojis(burners)

    assert burners["Custom"]["emoji"] == reserved
    assert burners["Automatic"]["emoji"] != reserved


def test_emoji_labels_render_on_list_and_map():
    burners = {"Alice": _node()}
    frame = Image.new("RGB", (480, 800), "white")
    blank = frame.copy()

    draw_node_labels(burners, ImageDraw.Draw(frame))

    assert burners["Alice"]["emoji"]
    assert ImageChops.difference(frame, blank).getbbox() is not None


def test_unicode_emoji_labels_render_on_list_and_map():
    rocket_frame = Image.new("RGB", (480, 800), "white")
    tent_frame = rocket_frame.copy()

    draw_node_labels(
        {"Alice": {**_node(), "emoji": "🚀"}}, ImageDraw.Draw(rocket_frame)
    )
    draw_node_labels({"Alice": {**_node(), "emoji": "⛺"}}, ImageDraw.Draw(tent_frame))

    assert ImageChops.difference(rocket_frame, tent_frame).getbbox() is not None


def test_top_list_entry_uses_12_hour_am_pm_timestamp():
    detail = _detail_text("Alice", _node(), "♥")

    assert detail.startswith("♥ Alice: 12:00+The Man @ ")
    assert detail.endswith((" AM", " PM"))
    assert " at " not in detail


def test_chat_panel_draws_separator_and_recent_message_text():
    frame = Image.new("RGB", (480, 800), "white")
    blank = frame.copy()
    draw_chat_messages(
        ImageDraw.Draw(frame),
        [
            {
                "sender": "Alice",
                "rx_time": 1_786_649_028,
                "received_at": "2026-08-19T00:00:00Z",
                "text": "Meet at the Man",
            }
        ],
        location_count=1,
    )

    # list starts at y=8 now; separator = 8 + 1*14 + 3 = 25, message at y=31
    assert frame.getpixel((20, 25)) == (0, 0, 0)
    assert (
        ImageChops.difference(frame, blank).crop((0, 31, 480, 48)).getbbox() is not None
    )


def test_position_time_uses_unpadded_12_hour_clock():
    assert _clock_time(datetime(2026, 8, 19, 13, 5, tzinfo=timezone.utc)) == "1:05 PM"
    assert (
        _clock_time(datetime(2026, 8, 19, 0, 5, 9, tzinfo=timezone.utc), seconds=True)
        == "12:05:09 AM"
    )


def test_weather_alert_cli_flag_is_explicitly_controllable():
    parser = display_map.build_parser()

    assert parser.parse_args([]).weather_alerts == True
    assert parser.parse_args(["--weather-alerts"]).weather_alerts == True
    assert parser.parse_args(["--no-weather-alerts"]).weather_alerts == False


def test_chat_panel_cli_flag_defaults_on_and_can_be_disabled():
    parser = display_map.build_parser()

    assert parser.parse_args([]).no_chat is False
    assert parser.parse_args(["--no-chat"]).no_chat is True


def test_emoji_labels_never_use_requested_yellow():
    burners = {"Alice": _node()}
    frame = Image.new("RGB", (480, 800), "white")

    draw_node_labels(
        burners,
        ImageDraw.Draw(frame),
        colors=((255, 255, 0),),
    )

    pixels = set(frame.get_flattened_data())
    assert (255, 255, 0) not in pixels
    assert (0, 0, 0) in pixels


def test_friend_metadata_overrides_emoji_without_filtering_locations():
    class Store:
        def get_friends(self):
            return [{"node_id": "!1234", "emoji": "♥"}]

    burners, _ = display_map._apply_friend_emojis(
        {"Alice": _node(), "Unknown": {**_node(), "node_id": "!9999"}}, Store()
    )

    assert list(burners) == ["Alice", "Unknown"]
    assert burners["Alice"]["emoji"] == "♥"
    assert "emoji" not in burners["Unknown"]


def test_map_frame_is_rgb_and_has_supported_dimensions():
    base = display_map._load_map()
    frame, _ = display_map._new_frame(base)

    assert frame.mode == "RGB"
    assert frame.size == (480, 800)


def test_map_frame_displays_updated_timestamp_in_bottom_right_corner():
    base = display_map._load_map()
    without_timestamp = display_map._new_frame(base, updated_at=0)[0]
    frame, _ = display_map._new_frame(base, updated_at=1_786_649_028)

    changed = ImageChops.difference(frame, without_timestamp)
    assert changed.getbbox() is not None
    assert changed.crop((240, 760, 480, 800)).getbbox() is not None


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

    class FakeHistory:
        def __init__(self, path):
            pass

        def latest_positions(self):
            return []

        def close(self):
            events.append("history-close")

    monkeypatch.setattr(display_map, "_init_epd", FakeEPD)
    monkeypatch.setattr(display_map, "HistoryStore", FakeHistory)
    monkeypatch.setattr(display_map, "connect_mesh_serial", stop_at_mesh_connection)
    args = SimpleNamespace(no_friends=True, screen=False, debug=False)

    with pytest.raises(RuntimeError, match="stop test"):
        display_map.main(args)

    assert events == ["display", "connect", "history-close", "sleep"]


def test_persisted_positions_are_drawn_before_mesh_connection(monkeypatch):
    events = []

    class FakeEPD:
        def getbuffer(self, frame):
            return frame

        def display(self, frame):
            events.append("display")

        def sleep(self):
            events.append("sleep")

    class FakeHistory:
        def __init__(self, path):
            pass

        def latest_positions(self):
            return [
                (
                    "!1234",
                    {
                        "user": {"longName": "Alice"},
                        "position": {
                            "latitude": 40.783247,
                            "longitude": -119.207884,
                            "time": 100,
                        },
                    },
                )
            ]

        def close(self):
            events.append("history-close")

    def cached_burners(*args):
        events.append("restore-render")
        return {"Alice": _node()}

    def stop_at_mesh_connection():
        events.append("connect")
        raise RuntimeError("stop test after startup")

    monkeypatch.setattr(display_map, "_init_epd", FakeEPD)
    monkeypatch.setattr(display_map, "HistoryStore", FakeHistory)
    monkeypatch.setattr(display_map, "_cached_burners", cached_burners)
    monkeypatch.setattr(display_map, "connect_mesh_serial", stop_at_mesh_connection)

    with pytest.raises(RuntimeError, match="stop test"):
        display_map.main(SimpleNamespace(no_friends=True, screen=False, debug=False))

    assert events == [
        "restore-render",
        "display",
        "connect",
        "history-close",
        "sleep",
    ]


def test_integrated_weather_reuses_map_interface_and_failures_do_not_stop_map(
    monkeypatch,
):
    events = []

    class FakeEPD:
        def getbuffer(self, frame):
            return frame

        def display(self, frame):
            events.append("display")

        def sleep(self):
            events.append("epd-sleep")

    class FakeHistory:
        def __init__(self, path):
            pass

        def latest_positions(self):
            return []

        def record_positions(self, burners):
            return 0

        def close(self):
            events.append("history-close")

    class FakeInterface:
        def __init__(self):
            self.nodes = {}

        def close(self):
            events.append("interface-close")

    interface = FakeInterface()

    class FakeScheduler:
        def __init__(self, scheduler_interface):
            assert scheduler_interface is interface
            events.append("scheduler-init")

        def maybe_send(self):
            events.append("weather-attempt")
            raise RuntimeError("weather unavailable")

    class FakeLiveScheduler:
        def __init__(self, scheduler_interface, poll_interval_seconds=120):
            assert scheduler_interface is interface
            events.append("live-scheduler-init")

        def maybe_send(self):
            events.append("live-weather-attempt")
            raise RuntimeError("live weather unavailable")

    def stop_after_first_loop(seconds):
        events.append("sleep")
        raise RuntimeError("stop test after first loop")

    monkeypatch.setattr(display_map, "_init_epd", FakeEPD)
    monkeypatch.setattr(display_map, "HistoryStore", FakeHistory)
    monkeypatch.setattr(display_map, "connect_mesh_serial", lambda: interface)
    monkeypatch.setattr(display_map, "WeatherAlertScheduler", FakeScheduler)
    monkeypatch.setattr(display_map, "MeshAlertScheduler", FakeLiveScheduler)
    monkeypatch.setattr(display_map.time, "sleep", stop_after_first_loop)

    with pytest.raises(RuntimeError, match="stop test after first loop"):
        display_map.main(
            SimpleNamespace(
                no_friends=True,
                screen=False,
                debug=False,
                weather_alerts=True,
            )
        )

    assert events == [
        "display",
        "scheduler-init",
        "live-scheduler-init",
        "weather-attempt",
        "live-weather-attempt",
        "sleep",
        "interface-close",
        "history-close",
        "epd-sleep",
    ]
