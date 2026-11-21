"""Dartboard geometry and scoring.

Board coordinate system (millimetres):
    origin = bullseye centre, +x = right, +y = up (towards the 20),
    +z = out of the board towards the player.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Standard WDF/PDC steel-tip dimensions (radius, mm)
R_BULL = 6.35          # double bull (50)
R_OUTER_BULL = 15.9    # single bull (25)
R_TRIPLE_IN = 99.0
R_TRIPLE_OUT = 107.0
R_DOUBLE_IN = 162.0
R_DOUBLE_OUT = 170.0

# Numbers clockwise starting at the top
SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]
SECTOR_DEG = 18.0


@dataclass(frozen=True)
class Hit:
    """A scored dart."""
    sector: int      # 1..20, 25 for bull, 0 for miss
    multiplier: int  # 0 (miss), 1, 2, 3
    x: float = 0.0
    y: float = 0.0

    @property
    def score(self) -> int:
        return self.sector * self.multiplier

    @property
    def label(self) -> str:
        if self.multiplier == 0:
            return "MISS"
        if self.sector == 25:
            return "BULL" if self.multiplier == 2 else "25"
        return {1: "S", 2: "D", 3: "T"}[self.multiplier] + str(self.sector)

    def to_dict(self) -> dict:
        return {"sector": self.sector, "multiplier": self.multiplier,
                "score": self.score, "label": self.label,
                "x": round(self.x, 2), "y": round(self.y, 2)}


def sector_angle(number: int) -> float:
    """Centre angle (degrees, CCW from +x) of a sector number."""
    idx = SECTORS.index(number)
    return 90.0 - idx * SECTOR_DEG


def score_point(x: float, y: float) -> Hit:
    """Score a board position (mm)."""
    r = math.hypot(x, y)
    if r <= R_BULL:
        return Hit(25, 2, x, y)
    if r <= R_OUTER_BULL:
        return Hit(25, 1, x, y)
    if r > R_DOUBLE_OUT:
        return Hit(0, 0, x, y)
    ang = math.degrees(math.atan2(y, x))
    idx = int(round((90.0 - ang) / SECTOR_DEG)) % 20
    sector = SECTORS[idx]
    if R_TRIPLE_IN <= r <= R_TRIPLE_OUT:
        mult = 3
    elif R_DOUBLE_IN <= r <= R_DOUBLE_OUT:
        mult = 2
    else:
        mult = 1
    return Hit(sector, mult, x, y)


def polar(r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return r * math.cos(a), r * math.sin(a)


def calibration_points() -> list[tuple[float, float]]:
    """Board points used for camera calibration.

    The outer edge of the double ring at the four wire crossings
    20|1, 6|10, 3|19, 11|14 – easy to see from any camera angle.
    """
    pts = []
    for a in (81.0, -9.0, -99.0, 171.0):  # 20/1, 6/10, 3/19, 11/14 boundaries
        pts.append(polar(R_DOUBLE_OUT, a))
    return pts


CALIBRATION_NAMES = ["20|1", "6|10", "3|19", "11|14"]
