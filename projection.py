"""Map projection: GPS (lat, lon) → screen pixel (x, y).

Uses a similarity transform derived from anchor points — the user provides
2+ known GPS→pixel pairs, and the module computes scale, rotation, and
translation automatically.  No hardcoded bounding boxes, no magic angles.

Usage:
    proj = MapProjection([
        (man_lat, man_lon, man_px_x, man_px_y),
        (temple_lat, temple_lon, temple_px_x, temple_px_y),
    ])
    x, y = proj.gps_to_pixel(lat, lon)
"""

import math


class MapProjection:
    """Similarity transform from geographic to pixel coordinates.

    Anchor points are (lat, lon, screen_x, screen_y) tuples.
    The first anchor defines the origin; the second defines scale + rotation.
    Additional anchors (if provided) are used to verify consistency.
    """

    def __init__(
        self,
        anchors: list[tuple[float, float, float, float]],
        feet_per_degree: float = 364000.0,
    ):
        if len(anchors) < 2:
            raise ValueError("Need at least 2 anchor points (GPS → pixel pairs)")

        self.feet_per_degree = feet_per_degree
        self._anchors = anchors

        lat0, lon0, px0, py0 = anchors[0]
        lat1, lon1, px1, py1 = anchors[1]

        self.origin_gps = (lat0, lon0)
        self.origin_px = (px0, py0)

        cos_lat = math.cos(math.radians(lat0))

        # Vector from anchor 0 to anchor 1 in local feet
        dx_ft = (lon1 - lon0) * feet_per_degree * cos_lat
        dy_ft = (lat1 - lat0) * feet_per_degree

        # Vector in pixel space (PIL y-axis points down)
        dx_px = px1 - px0
        dy_px = py1 - py0

        # Scale: pixels per foot
        dist_ft = math.hypot(dx_ft, dy_ft)
        dist_px = math.hypot(dx_px, dy_px)
        if dist_ft < 1.0 or dist_px < 1.0:
            raise ValueError(
                "Anchor points are too close together — need well-separated points"
            )
        self._scale = dist_px / dist_ft  # px/ft

        # Rotation: angle from geographic (north-up) to pixel (screen-y-down)
        angle_geo = math.atan2(dy_ft, dx_ft)  # geographic bearing
        angle_px = math.atan2(-dy_px, dx_px)  # pixel bearing (y inverted)
        self._rotation = angle_px - angle_geo

        # Precompute the 2×2 matrix:  [dx_px] = M * [dx_ft; dy_ft]
        # After rotation, negate y because PIL's y-axis points down
        c = self._scale * math.cos(self._rotation)
        s = self._scale * math.sin(self._rotation)
        self._m00 = c  # maps dx_ft → dx_px
        self._m01 = -s  # maps dy_ft → dx_px
        self._m10 = -s  # maps dx_ft → dy_px  (negated for PIL y-down)
        self._m11 = -c  # maps dy_ft → dy_px  (negated for PIL y-down)

    @property
    def scale_px_per_ft(self) -> float:
        """Pixels per foot at the origin latitude."""
        return self._scale

    @property
    def rotation_deg(self) -> float:
        """Rotation from geographic north to screen-up, in degrees."""
        return math.degrees(self._rotation)

    def gps_to_pixel(self, lat: float, lon: float) -> tuple[float, float]:
        """Convert a GPS coordinate to a screen pixel (x, y)."""
        lat0, lon0 = self.origin_gps
        cos_lat = math.cos(math.radians(lat0))

        dx_ft = (lon - lon0) * self.feet_per_degree * cos_lat
        dy_ft = (lat - lat0) * self.feet_per_degree

        dx_px = self._m00 * dx_ft + self._m01 * dy_ft
        dy_px = self._m10 * dx_ft + self._m11 * dy_ft

        return (self.origin_px[0] + dx_px, self.origin_px[1] + dy_px)

    def pixel_to_gps(self, px: int, py: int) -> tuple[float, float]:
        """Convert a screen pixel back to a GPS coordinate."""
        lat0, lon0 = self.origin_gps
        px0, py0 = self.origin_px

        dx_px = px - px0
        dy_px = py - py0

        # Invert the 2×2 matrix [m00 m01; m10 m11]
        # For a similarity transform, inverse = 1/(scale²) * [m00 -m01; -m10 m11]
        det = self._m00 * self._m11 - self._m01 * self._m10
        if abs(det) < 1e-20:
            raise ValueError("Singular projection matrix")

        dx_ft = (self._m11 * dx_px - self._m01 * dy_px) / det
        dy_ft = (-self._m10 * dx_px + self._m00 * dy_px) / det

        cos_lat = math.cos(math.radians(lat0))
        lon = lon0 + dx_ft / (self.feet_per_degree * cos_lat)
        lat = lat0 + dy_ft / self.feet_per_degree

        return (lat, lon)

    def dump(self) -> str:
        """Return a human-readable summary of the projection."""
        lat0, lon0 = self.origin_gps
        px0, py0 = self.origin_px
        lines = [
            f"MapProjection ({len(self._anchors)} anchors)",
            f"  origin GPS:  ({lat0:.6f}, {lon0:.6f})",
            f"  origin px:   ({px0:.0f}, {py0:.0f})",
            f"  scale:       {self._scale:.6f} px/ft  ({1 / self._scale:.1f} ft/px)",
            f"  rotation:    {self.rotation_deg:.2f}°",
        ]
        for i, (lat, lon, px, py) in enumerate(self._anchors):
            cpx, cpy = self.gps_to_pixel(lat, lon)
            err = math.hypot(cpx - px, cpy - py)
            lines.append(
                f"  anchor[{i}]:  ({lat:.6f}, {lon:.6f}) → ({px:.0f}, {py:.0f})  "
                f"reproj=({cpx:.1f}, {cpy:.1f}) err={err:.1f}px"
            )
        return "\n".join(lines)
