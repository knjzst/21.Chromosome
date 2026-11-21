"""Camera calibration.

1. The user clicks the 4 calibration points (outer double wire at 20|1,
   6|10, 3|19, 11|14) once per camera  ->  rough homography.
2. `refine` aligns a rendered board model with the live image (ECC, sub-pixel)
   so a sloppy click does not cost accuracy.  It is cheap enough to re-run
   automatically while the board is idle (e.g. after a camera was bumped).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from . import board as B
from .geometry import CameraGeometry, homography_dlt
from .sim import TEX_MM, TEX_PX, board_texture

_GRAY_TEX = None


def _template_gray():
    global _GRAY_TEX
    if _GRAY_TEX is None:
        _GRAY_TEX = cv2.cvtColor(board_texture(), cv2.COLOR_BGR2GRAY)
    return _GRAY_TEX


def _tex_to_board():
    s = 2 * TEX_MM / TEX_PX
    return np.array([[s, 0, -TEX_MM], [0, -s, TEX_MM], [0, 0, 1.0]])


def from_clicks(image_pts, image_size) -> CameraGeometry:
    bp = np.array(B.calibration_points())
    return CameraGeometry(homography_dlt(bp, np.asarray(image_pts, float)), image_size)


def board_mask(geom: CameraGeometry, r_mm=B.R_DOUBLE_OUT - 1.0) -> np.ndarray:
    ang = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    ring = np.c_[r_mm * np.cos(ang), r_mm * np.sin(ang)]
    pts = geom.board_to_image(ring).astype(np.int32)
    m = np.zeros((geom.h, geom.w), np.uint8)
    cv2.fillPoly(m, [pts], 255)
    return m


def refine(image: np.ndarray, geom: CameraGeometry, iterations=60,
           levels=2) -> tuple[CameraGeometry, float]:
    """Sub-pixel refinement of the board homography. Returns (geom, ecc)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    H = geom.H.copy()
    size = (geom.w, geom.h)
    score = 0.0
    for lvl in reversed(range(levels)):
        s = 0.5 ** lvl
        S = np.diag([s, s, 1.0])
        Hs = S @ H
        w, h = int(round(size[0] * s)), int(round(size[1] * s))
        tpl = cv2.warpPerspective(_template_gray(), Hs @ _tex_to_board(), (w, h),
                                  flags=cv2.INTER_AREA)
        g = CameraGeometry(Hs, (w, h))
        mask = board_mask(g)
        img = cv2.resize(gray, (w, h), interpolation=cv2.INTER_AREA) if s != 1 else gray
        W = np.eye(3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iterations, 1e-5)
        try:
            score, W = cv2.findTransformECC(tpl, img, W, cv2.MOTION_HOMOGRAPHY,
                                            crit, mask, 5)
        except cv2.error:
            return geom, 0.0
        Hs = W.astype(float) @ Hs
        H = np.linalg.inv(S) @ Hs
        H /= H[2, 2]
    return CameraGeometry(H, size), float(score)


def save(path: str | Path, geoms: list[CameraGeometry], extra: dict | None = None):
    data = {"cameras": [g.to_dict() for g in geoms]}
    if extra:
        data.update(extra)
    Path(path).write_text(json.dumps(data, indent=2))


def load(path: str | Path) -> tuple[list[CameraGeometry], dict]:
    data = json.loads(Path(path).read_text())
    geoms = [CameraGeometry(np.array(c["H"]), tuple(c["image_size"]))
             for c in data["cameras"]]
    return geoms, data
