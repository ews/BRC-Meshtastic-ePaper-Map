"""Tests for the populated desktop map mockup."""

import config as c
import tools.full_mockup as full_mockup
from tools.full_mockup import build_mockup


def test_mockup_has_requested_number_of_people_and_brc_addresses():
    frame, burners = build_mockup(seed=42, people=6)

    assert frame.mode == "RGB"
    assert frame.size == (c.WIDTH, c.HEIGHT)
    assert len(burners) == 6
    assert len(set(burners)) == 6
    assert all(" + " in data["bm_coordinates"] for data in burners.values())
    emojis = [data["emoji"] for data in burners.values()]
    assert len(set(emojis)) == len(emojis)


def test_default_mockup_has_five_or_six_visible_people():
    _, burners = build_mockup(seed=7)

    assert len(burners) in (5, 6)
    for data in burners.values():
        x, y = data["image_coordinates"]
        assert 0 <= x < c.WIDTH
        assert 0 <= y < c.HEIGHT


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
