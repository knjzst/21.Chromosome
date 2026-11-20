"""Dart tip detection in a single camera image (classical CV, no neural net).

Given a reference frame (board before the throw) and the current frame
(after the dart landed and the image is stable), find the new dart and
locate its tip in pixel coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import CameraGeometry
from . import board as B


@dataclass
class TipResult:
    tip: np.ndarray          # (u, v) image px
    board: np.ndarray        # (x, y) mm
    cov: np.ndarray          # 2x2 mm^2
    area: int                # changed pixels
    quality: float           # 0..1


def roi_mask(geom: CameraGeometry, margin_mm=15.0, height_mm=170.0) -> np.ndarray:
    """Image area where a dart on the board can appear (board disc + the
    space in front of it where barrel and flight are)."""
    ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    r = B.R_DOUBLE_OUT + margin_mm
    ring = np.c_[r * np.cos(ang), r * np.sin(ang)]
    pts = []
    for z in (0.0, height_mm):
        pts.append(geom.project(np.c_[ring, np.full(len(ring), z)]))
    pts = np.vstack(pts)
    pts = pts[np.isfinite(pts).all(1)]
    hull = cv2.convexHull(pts.astype(np.float32)).astype(np.int32)
    m = np.zeros((geom.h, geom.w), np.uint8)
    cv2.fillConvexPoly(m, hull, 255)
    return m


def change_mask(ref: np.ndarray, cur: np.ndarray, roi: np.ndarray | None,
                thresh: int = 22) -> np.ndarray:
    if ref.ndim == 3:
        b, g, r = cv2.split(cv2.absdiff(ref, cur))
        d = cv2.max(cv2.max(b, g), r)
    else:
        d = cv2.absdiff(ref, cur)
    d = cv2.GaussianBlur(d, (3, 3), 0)
    _, m = cv2.threshold(d, thresh, 255, cv2.THRESH_BINARY)
    if roi is not None:
        m = cv2.bitwise_and(m, roi)
    return m


def _main_blob(mask: np.ndarray, min_area: int):
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1
    main = order[0]
    if stats[main, cv2.CC_STAT_AREA] < min_area:
        return None
    # The diff only contains the NEW dart (older darts are in the reference),
    # so every non-trivial component belongs to it – e.g. a dart split in two
    # by an older dart in front of it.
    main_area = stats[main, cv2.CC_STAT_AREA]
    keep = [k for k in order if stats[k, cv2.CC_STAT_AREA] >= max(8, 0.02 * main_area)]
    ys, xs = np.nonzero(np.isin(lab, keep))
    pts = np.c_[xs, ys].astype(np.float32)
    return pts


def find_tip(ref: np.ndarray, cur: np.ndarray, geom: CameraGeometry,
             roi: np.ndarray | None = None, thresh: int = 22,
             min_area: int = 40, pixel_sigma: float = 1.0,
             tip_offset: float = 0.0,
             max_radius_mm: float = 225.0) -> TipResult | None:
    mask = change_mask(ref, cur, roi, thresh)
    pts = _main_blob(mask, min_area)
    if pts is None:
        return None
    area = len(pts)

    # 1) coarse axis through the whole blob
    vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    axis = np.array([vx, vy])
    s = (pts - [x0, y0]) @ axis
    ends = [pts[np.argmin(s)], pts[np.argmax(s)]]

    # 2) which end is the tip?  The barrel must point from the tip in the
    #    direction predicted by the camera pose (board normal projection).
    best, best_score = None, -np.inf
    for i, e in enumerate(ends):
        other = ends[1 - i]
        bxy = geom.image_to_board(e)[0]
        dd = geom.dart_direction(bxy)
        v = other - e
        sc = float(v @ dd) / (np.linalg.norm(v) + 1e-9)
        if sc > best_score:
            best, best_score = i, sc
    sign = -1.0 if best == 0 else 1.0  # tip is at min(s) if best == 0
    t = s * sign  # t: 0..len, small = tip side
    t = t - t.min()
    length = t.max()
    if length < 8:
        return None

    # 3) refine: fit a line to the thin front part (point + barrel) only
    front = pts[t < max(0.45 * length, 10)]
    if len(front) >= 6:
        fx, fy, fx0, fy0 = cv2.fitLine(front, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        fa = np.array([fx, fy])
        if fa @ (axis * sign) < 0:
            fa = -fa
        # keep pixels close to the front line
        rel = front - [fx0, fy0]
        perp = np.abs(rel @ np.array([-fa[1], fa[0]]))
        near = front[perp < 2.5]
        if len(near) < 3:
            near = front
        tt = (near - [fx0, fy0]) @ fa
        tmin = tt.min()
        # average the few extreme pixels for sub-pixel stability; the
        # tip_offset compensates the blur/threshold bias (+ = towards barrel)
        sel = tt < tmin + 1.0
        along = tmin + tip_offset
        perp_c = ((near[sel] - [fx0, fy0]) @ np.array([-fa[1], fa[0]])).mean()
        tip = np.array([fx0, fy0]) + fa * along + np.array([-fa[1], fa[0]]) * perp_c
    else:
        tip = ends[best].astype(float)

    bxy = geom.image_to_board(tip)[0]
    if not np.all(np.isfinite(bxy)) or np.hypot(*bxy) > max_radius_mm:
        return None  # tip hidden (e.g. behind another dart) -> implausible
    cov = geom.board_covariance(bxy, pixel_sigma)
    q = float(np.clip((best_score + 1) / 2, 0, 1))
    return TipResult(tip=tip, board=bxy, cov=cov, area=area, quality=q)
