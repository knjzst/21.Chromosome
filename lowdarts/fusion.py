"""Fuse per-camera tip estimates into one board position.

Each camera's estimate is accurate across its line of sight but poor along
it (depth).  Weighting with the inverse covariances makes three cameras at
120 deg behave like a proper triangulation – at the cost of a 2x2 solve.
"""
from __future__ import annotations

import numpy as np

from .detector import TipResult


def fuse(results: list[TipResult], gate: float = 9.0,
         floor_mm: float = 0.3) -> tuple[np.ndarray, np.ndarray, list[int]] | None:
    """Return (xy, cov, used_indices) or None.

    gate: Mahalanobis^2 threshold for outlier rejection.
    floor_mm: minimum isotropic std (model error) added to every camera.
    """
    items = [(i, r) for i, r in enumerate(results) if r is not None]
    if not items:
        return None

    def solve(sel):
        A = np.zeros((2, 2))
        b = np.zeros(2)
        for _, r in sel:
            C = r.cov + floor_mm ** 2 * np.eye(2)
            W = np.linalg.inv(C)
            A += W
            b += W @ r.board
        cov = np.linalg.inv(A)
        return cov @ b, cov

    sel = items
    while True:
        xy, cov = solve(sel)
        if len(sel) <= 2:
            break
        d2 = []
        for i, r in sel:
            C = r.cov + floor_mm ** 2 * np.eye(2)
            e = r.board - xy
            d2.append(float(e @ np.linalg.inv(C) @ e))
        worst = int(np.argmax(d2))
        if d2[worst] <= gate:
            break
        sel = [s for k, s in enumerate(sel) if k != worst]
    if len(sel) == 2:
        # two left: if they disagree badly, trust the more certain one
        (_, a), (_, b) = sel
        C = a.cov + b.cov + 2 * floor_mm ** 2 * np.eye(2)
        e = a.board - b.board
        if float(e @ np.linalg.inv(C) @ e) > 4 * gate:
            sel = [min(sel, key=lambda s: np.trace(s[1].cov))]
            xy, cov = solve(sel)
    return xy, cov, [i for i, _ in sel]
