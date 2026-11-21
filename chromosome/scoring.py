"""Scoring: Boardpunkt (mm, Ursprung Bull, y zur 20) -> Segment und Punktzahl."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Config

# Segmentreihenfolge im Uhrzeigersinn, beginnend oben bei der 20
SEGMENTS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]


@dataclass
class Score:
    label: str          # z. B. "T20", "D16", "25", "BULL", "MISS"
    value: int
    segment: int        # 0 bei Bull/Miss
    ring: str           # "single" | "double" | "triple" | "outer_bull" | "bull" | "miss"


def score_point(x_mm: float, y_mm: float, cfg: Config) -> Score:
    b = cfg.section("board")
    r = math.hypot(x_mm, y_mm)

    if r <= float(b["bull_inner_r"]):
        return Score("BULL", 50, 0, "bull")
    if r <= float(b["bull_outer_r"]):
        return Score("25", 25, 0, "outer_bull")
    if r > float(b["double_outer_r"]):
        return Score("MISS", 0, 0, "miss")

    # Winkel: 0 = oben (20), im Uhrzeigersinn; Segmente sind je 18° breit
    angle = math.degrees(math.atan2(x_mm, y_mm))  # x=sin, y=cos -> 0° oben
    idx = int(((angle + 9.0) % 360.0) // 18.0)
    seg = SEGMENTS[idx]

    if float(b["triple_inner_r"]) <= r <= float(b["triple_outer_r"]):
        return Score(f"T{seg}", 3 * seg, seg, "triple")
    if float(b["double_inner_r"]) <= r <= float(b["double_outer_r"]):
        return Score(f"D{seg}", 2 * seg, seg, "double")
    return Score(str(seg), seg, seg, "single")
