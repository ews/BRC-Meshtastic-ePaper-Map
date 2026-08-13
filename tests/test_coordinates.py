"""Tests for BRC address conversion."""

import config as c
from coordinates import gps_to_burning_man


def test_position_inside_esplanade_is_open_playa():
    lat, lon = c.projection.pixel_to_gps(c.man_svg[0] + 50, c.man_svg[1])

    assert gps_to_burning_man(lat, lon).endswith(" + Open Playa")
