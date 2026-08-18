"""Tests for the populated desktop map mockup."""

import config as c
import tools.full_mockup as full_mockup
from coordinates import distance_ft, gps_to_image_coordinates
from tools.full_mockup import build_mockup


def test_mockup_has_requested_number_of_people_and_brc_addresses():
    frame, burners = build_mockup(seed=42, people=6)

    assert frame.mode == "RGB"
    assert frame.size == (c.WIDTH, c.HEIGHT)
    assert len(burners) == 6
    assert len(set(burners)) == 6
    assert all(
        "+" in data["bm_coordinates"]
        or "ft from Man" in data["bm_coordinates"]
        or "+Trash Fence" in data["bm_coordinates"]
        for data in burners.values()
    )
    emojis = [data["emoji"] for data in burners.values()]
    assert len(set(emojis)) == len(emojis)


def test_default_mockup_covers_non_city_areas_and_every_street_ring():
    _, burners = build_mockup(seed=7)

    assert len(burners) == 15
    zones = [
        full_mockup._address_zone(data["bm_coordinates"])
        for data in burners.values()
    ]
    assert zones.count("Near Man") == 1
    assert zones.count("Beyond City") == 1
    assert zones.count("Trash Fence") == 1
    assert set(c.STREET_NAMES).issubset(zones)
    for data in burners.values():
        x, y = data["image_coordinates"]
        assert 0 <= x < c.WIDTH
        assert 0 <= y < c.HEIGHT
        lat = data["coordinates"]["latitude"]
        lon = data["coordinates"]["longitude"]
        radius_ft = distance_ft((c.MAN_LAT, c.MAN_LONG), (lat, lon))
        assert full_mockup.NEAR_MAN_MIN_DISTANCE_FT <= radius_ft
        assert radius_ft <= c.distance_man_to_end_trashfence_ft
        assert (x, y) == gps_to_image_coordinates((lat, lon, "test burner"))
        assert full_mockup._inside_trash_fence((x, y))
        zone = full_mockup._address_zone(data["bm_coordinates"])
        if zone in c.STREET_NAMES:
            assert 2 <= full_mockup._clock_value(data["bm_coordinates"]) <= 10
        elif zone == "Beyond City":
            assert radius_ft >= full_mockup.BEYOND_CITY_MIN_DISTANCE_FT
            assert not 2 <= full_mockup._clock_value(data["bm_coordinates"]) <= 10
        elif zone == "Trash Fence":
            assert data["bm_coordinates"].endswith("+Trash Fence")


def test_location_updates_keep_burner_identity_and_emoji():
    numbers = list(range(10, 25))
    _, first = build_mockup(seed=1, people=15, burner_numbers=numbers)
    _, second = build_mockup(seed=2, people=15, burner_numbers=numbers)

    assert list(first) == list(second)
    assert [data["emoji"] for data in first.values()] == [
        data["emoji"] for data in second.values()
    ]
    assert any(
        first[name]["image_coordinates"] != second[name]["image_coordinates"]
        for name in first
    )
    assert any(
        full_mockup._address_zone(first[name]["bm_coordinates"])
        != full_mockup._address_zone(second[name]["bm_coordinates"])
        for name in first
    )


def test_epaper_preview_displays_and_sleeps(monkeypatch):
    events = []

    class FakeEPD:
        def getbuffer(self, frame):
            events.append(("buffer", frame.size))
            return b"packed"

        def display(self, buffer):
            events.append(("display", buffer))

        def sleep(self):
            events.append(("sleep",))

    monkeypatch.setattr(full_mockup, "_init_epd", FakeEPD)
    frame, _ = build_mockup(seed=1, people=5)

    full_mockup.display_on_epaper(frame)

    assert events == [
        ("buffer", (c.WIDTH, c.HEIGHT)),
        ("display", b"packed"),
        ("sleep",),
    ]


def test_live_epaper_mockup_uses_start_to_start_interval(monkeypatch, tmp_path):
    displays = []
    sleeps = []
    clock = iter((100.0, 112.0, 160.0))
    monkeypatch.setattr(full_mockup, "display_on_epaper", displays.append)
    monkeypatch.setattr(full_mockup.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(full_mockup.time, "sleep", sleeps.append)

    burners = full_mockup.run_mockup(
        seed=9,
        output=tmp_path / "mockup.png",
        epaper=True,
        show=False,
        interval=60,
        frames=2,
    )

    assert len(displays) == 2
    assert len(burners) == 15
    assert sleeps == [48.0]
