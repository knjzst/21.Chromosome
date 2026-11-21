"""Computer opponents: aim at a sensible target, scatter like a human.

Each level is a throwing accuracy (Gaussian scatter in mm).  The levels are
calibrated so their 501 averages roughly match the label (see tests).
"""
from __future__ import annotations

import math
import random

from . import board as B
from .board import Hit
from .game import parse_label

# level -> scatter sigma (mm); level n averages about 10*n + 10 (level 1 ~ 20, level 11 ~ 120)
LEVELS = {1: 53, 2: 31, 3: 21.7, 4: 16.7, 5: 13.9, 6: 11.5, 7: 9.6, 8: 7.9, 9: 6.6, 10: 5.7, 11: 4.7}


def aim_point(label: str) -> tuple[float, float]:
    h = parse_label(label)
    if h.sector == 25:
        return (0.0, 0.0) if h.multiplier == 2 else (0.0, 11.0)
    r = {1: 134.0, 2: 166.0, 3: 103.0}[h.multiplier]
    return B.polar(r, B.sector_angle(h.sector))


def throw_at(label: str, sigma: float, rng: random.Random) -> Hit:
    x, y = aim_point(label)
    return B.score_point(x + rng.gauss(0, sigma), y + rng.gauss(0, sigma))


def choose_target(state: dict) -> str:
    mode = state["mode"]
    me = state["players"][state["current"]]
    if mode == "x01":
        if not me.get("opened", True):
            return "D20" if state.get("in_mode") == "double" else "T20"
        left = me["score"]
        if me.get("checkout"):
            return me["checkout"].split()[0]
        if left <= 40 and left % 2 == 1:
            return "S1"
        if left < 60 and state.get("out_mode") != "straight":
            return f"S{min(20, left - 32 if left > 32 else max(1, left - 16))}"
        return "T20"
    if mode == "cricket":
        open_t = [t for t in state["open_targets"] if me["marks"][str(t)] < 3] or state["open_targets"]
        t = max(open_t) if open_t else 20
        return "BULL" if t == 25 else f"T{t}"
    if mode in ("atc",):
        t = me.get("target") or 25
        ring = state.get("ring", "any")
        if t == 25:
            return "25"
        return {"double": "D", "triple": "T"}.get(ring, "S") + str(t)
    if mode == "bobs27":
        return state["target_label"]
    if mode == "shanghai":
        return f"T{state['target']}"
    return "T20"


class Bot:
    def __init__(self, level: int = 5, seed: int | None = None):
        self.level = max(1, min(11, int(level)))
        self.sigma = LEVELS[self.level]
        self.rng = random.Random(seed)

    def next_dart(self, state: dict) -> Hit:
        return throw_at(choose_target(state), self.sigma, self.rng)
