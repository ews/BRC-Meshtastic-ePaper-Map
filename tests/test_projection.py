"""Tests for projection.py — GPS ↔ pixel coordinate mapping."""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from projection import MapProjection


class TestMapProjection:
    """Core projection tests."""

    def test_two_anchors_identity(self):
        """Projection with no rotation or scaling (identity anchors)."""
        proj = MapProjection(
            [
                (40.0, -119.0, 100, 200),  # origin
                (40.0, -118.0, 300, 200),  # 1° east → 200px right
            ],
            feet_per_degree=364000,
        )
        # Origin should map to itself
        x, y = proj.gps_to_pixel(40.0, -119.0)
        assert abs(x - 100) < 0.1
        assert abs(y - 200) < 0.1

        # Second anchor should map to itself
        x, y = proj.gps_to_pixel(40.0, -118.0)
        assert abs(x - 300) < 0.1
        assert abs(y - 200) < 0.1

    def test_scale(self):
        """Scale should be correctly computed."""
        proj = MapProjection(
            [
                (40.0, -119.0, 0, 0),
                (40.0, -118.0, 200, 0),  # 1° east → 200px
            ],
            feet_per_degree=364000,
        )
        # At lat 40°, 1° lon = 364000 * cos(40°) ≈ 278,830 ft
        # Scale = 200 / 278,830 ≈ 0.000717 px/ft
        expected_scale = 200 / (364000 * math.cos(math.radians(40)))
        assert abs(proj.scale_px_per_ft - expected_scale) < 1e-8

    def test_rotation_north_up(self):
        """North-going GPS should map to up on screen (negative y in PIL)."""
        proj = MapProjection(
            [
                (40.0, -119.0, 100, 100),
                (41.0, -119.0, 100, 0),  # 1° north → 100px up
            ],
            feet_per_degree=364000,
        )
        # A point north of origin should go up (smaller y)
        x, y = proj.gps_to_pixel(40.5, -119.0)
        assert y < 100  # up from origin

    def test_rotation_east_right(self):
        """East-going GPS should map to right on screen."""
        proj = MapProjection(
            [
                (40.0, -119.0, 100, 100),
                (40.0, -118.0, 200, 100),  # east → right
            ],
            feet_per_degree=364000,
        )
        x, y = proj.gps_to_pixel(40.0, -118.5)
        assert x > 100  # right of origin

    def test_round_trip(self):
        """pixel_to_gps(gps_to_pixel(lat,lon)) should return original coords."""
        proj = MapProjection(
            [
                (40.783247, -119.207884, 240, 516),
                (40.788099, -119.201500, 311, 444),  # Temple NE of Man
            ],
            feet_per_degree=364000,
        )
        test_points = [
            (40.783247, -119.207884),  # The Man
            (40.788099, -119.201500),  # Temple
            (40.777372, -119.215612),  # Center Camp
            (40.792611, -119.220207),  # 9:00 & G
        ]
        for lat, lon in test_points:
            px, py = proj.gps_to_pixel(lat, lon)
            rlat, rlon = proj.pixel_to_gps(int(px), int(py))
            # Round-trip should be within ~25 ft (1px quantization at ~24 ft/px)
            from geopy.distance import geodesic as GD

            err = GD((lat, lon), (rlat, rlon)).feet
            assert err < 25, f"Round-trip error {err:.1f} ft for ({lat},{lon})"

    def test_rejects_single_anchor(self):
        """Should raise on fewer than 2 anchors."""
        with pytest.raises(ValueError, match="at least 2"):
            MapProjection([(40.0, -119.0, 100, 100)])

    def test_rejects_coincident_anchors(self):
        """Should raise when anchors are too close together."""
        with pytest.raises(ValueError, match="too close"):
            MapProjection(
                [
                    (40.0, -119.0, 100, 100),
                    (40.0, -119.0, 100, 100),  # same point
                ]
            )

    def test_dump(self):
        """dump() should return a string with key info."""
        proj = MapProjection(
            [
                (40.0, -119.0, 100, 200),
                (40.0, -118.0, 300, 200),
            ]
        )
        output = proj.dump()
        assert "MapProjection" in output
        assert "origin" in output.lower()
        assert "scale" in output.lower()
        assert "rotation" in output.lower()

    def test_projection_reproduces_anchors(self):
        """First 2 anchors (which define the transform) must be exact.

        Additional anchors beyond the first 2 are verification points —
        they may have small errors because the transform is computed only
        from the first 2 anchors.
        """
        proj = MapProjection(
            [
                (40.783247, -119.207884, 240, 516),
                (40.788099, -119.201500, 311, 444),
                (40.777372, -119.215612, 152, 603),  # verification only
            ]
        )
        # First 2 anchors define the transform — must be exact
        for lat, lon, px, py in [
            (40.783247, -119.207884, 240, 516),
            (40.788099, -119.201500, 311, 444),
        ]:
            rx, ry = proj.gps_to_pixel(lat, lon)
            assert abs(rx - px) < 0.5, f"anchor x: expected {px}, got {rx:.1f}"
            assert abs(ry - py) < 0.5, f"anchor y: expected {py}, got {ry:.1f}"

        # Third anchor is for verification — within 3px is acceptable
        rx, ry = proj.gps_to_pixel(40.777372, -119.215612)
        assert abs(rx - 152) < 3, f"verification anchor x off by {rx - 152:.1f}px"
        assert abs(ry - 603) < 3, f"verification anchor y off by {ry - 603:.1f}px"
