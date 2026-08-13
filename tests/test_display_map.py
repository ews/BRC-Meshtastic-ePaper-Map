"""Tests for display refresh decisions and E6 frame composition."""

import display_map


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


def test_map_frame_is_rgb_and_has_supported_dimensions():
    base = display_map._load_map()
    frame, _ = display_map._new_frame(base)

    assert frame.mode == "RGB"
    assert frame.size == (480, 800)
