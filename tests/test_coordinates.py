"""Tests for BRC address conversion."""

from geopy import Point
from geopy.distance import distance as geodesic_distance

import config as c
from coordinates import gps_to_burning_man


def test_position_inside_esplanade_uses_distance_from_man():
    lat, lon = c.projection.pixel_to_gps(c.man_svg[0] + 50, c.man_svg[1])

    address = gps_to_burning_man(lat, lon)
    assert "ft from Man" in address
    assert "Open Playa" not in address


def test_position_beyond_temple_uses_distance_from_man():
    gps = geodesic_distance(feet=4000).destination(
        Point(c.MAN_LAT, c.MAN_LONG), bearing=45
    )

    address = gps_to_burning_man(gps.latitude, gps.longitude)
    assert address.startswith(("11:59, ", "12:00, "))
    assert address.endswith("4000ft from Man")


def test_position_in_built_city_arc_uses_street_name():
    gps = geodesic_distance(feet=2950).destination(
        Point(c.MAN_LAT, c.MAN_LONG), bearing=225
    )

    assert gps_to_burning_man(gps.latitude, gps.longitude).endswith("+A")


def test_position_near_pentagon_uses_trash_fence_address():
    distance_inside_px = 100 * c.projection.scale_px_per_ft
    px = c.man_svg[0]
    py = c.man_svg[1] - c.svg_city_man_to_trashfence_pixel + distance_inside_px
    lat, lon = c.projection.pixel_to_gps(px, py)

    assert gps_to_burning_man(lat, lon).endswith("+Trash Fence")
