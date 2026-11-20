"""Synthetic camera renderer – used for tests, benchmarks and the demo mode.

Renders a textured dartboard as seen by a pinhole camera placed around the
board, and draws darts (thin tip, barrel, shaft, flight) in 3D.  Lets the
whole pipeline (calibration -> detection -> fusion -> scoring) be validated
without hardware.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import board as B
from .geometry import CameraGeometry

TEX_MM = 230.0   # texture covers [-TEX_MM, TEX_MM]
TEX_PX = 920


def board_texture() -> np.ndarray:
    n = TEX_PX
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    s = 2 * TEX_MM / n
    X = (xs + 0.5) * s - TEX_MM
    Y = TEX_MM - (ys + 0.5) * s
    r = np.hypot(X, Y)
    ang = np.degrees(np.arctan2(Y, X))
    idx = np.round((90.0 - ang) / B.SECTOR_DEG).astype(int) % 20
    even = (idx % 2 == 0)
    img = np.zeros((n, n, 3), np.uint8)
    img[:] = (40, 40, 40)  # surround (BGR)
    black, cream = (25, 25, 25), (170, 215, 230)
    red, green = (40, 40, 200), (60, 150, 40)
    single = np.where(even[..., None], black, cream)
    ring = np.where(even[..., None], red, green)
    m = r <= B.R_DOUBLE_OUT
    img[m] = single[m]
    rm = ((r >= B.R_TRIPLE_IN) & (r <= B.R_TRIPLE_OUT)) | \
         ((r >= B.R_DOUBLE_IN) & (r <= B.R_DOUBLE_OUT))
    img[rm] = ring[rm]
    img[r <= B.R_OUTER_BULL] = green
    img[r <= B.R_BULL] = red
    # wires
    wire = np.zeros((n, n), bool)
    for rr in (B.R_BULL, B.R_OUTER_BULL, B.R_TRIPLE_IN, B.R_TRIPLE_OUT,
               B.R_DOUBLE_IN, B.R_DOUBLE_OUT):
        wire |= np.abs(r - rr) < 0.6
    edge = (90.0 - ang) / B.SECTOR_DEG - 0.5
    frac = np.abs(edge - np.round(edge)) * B.SECTOR_DEG
    wire |= (frac * np.pi / 180 * r < 0.6) & (r > B.R_OUTER_BULL) & (r < B.R_DOUBLE_OUT)
    img[wire] = (190, 190, 190)
    return img


_TEX = None


def _tex():
    global _TEX
    if _TEX is None:
        _TEX = board_texture()
    return _TEX


def look_at(cam_pos, target=(0, 0, 0), up=(0, 1, 0)):
    c = np.asarray(cam_pos, float)
    z = np.asarray(target, float) - c
    z /= np.linalg.norm(z)
    x = np.cross(z, up)
    if np.linalg.norm(x) < 1e-6:
        x = np.cross(z, (1, 0, 0))
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])  # world -> camera
    t = -R @ c
    return R, t


class SimCamera:
    """A virtual camera mounted around the board.

    angle_deg: position around the board (90 = top, like the 20)
    """

    def __init__(self, angle_deg: float, size=(640, 480), fov_deg=90.0,
                 dist_mm=330.0, height_mm=95.0, noise=2.0, seed=0):
        self.w, self.h = size
        f = (self.w / 2) / math.tan(math.radians(fov_deg) / 2)
        self.K = np.array([[f, 0, self.w / 2], [0, f, self.h / 2], [0, 0, 1.0]])
        a = math.radians(angle_deg)
        pos = (dist_mm * math.cos(a), dist_mm * math.sin(a), height_mm)
        self.R, self.t = look_at(pos, target=(0, 0, 0), up=(0, 0, 1))
        self.P = self.K @ np.c_[self.R, self.t]
        self.H = self.P[:, [0, 1, 3]] / self.P[2, 3]
        self.noise = noise
        self.rng = np.random.default_rng(seed)
        # board mm -> image, texture px -> image
        s = 2 * TEX_MM / TEX_PX
        T = np.array([[s, 0, -TEX_MM], [0, -s, TEX_MM], [0, 0, 1.0]])
        Ht = self.H @ T
        self._base = cv2.warpPerspective(_tex(), Ht, (self.w, self.h),
                                         flags=cv2.INTER_LINEAR,
                                         borderValue=(70, 70, 70))
        self.darts: list[tuple] = []
        self.hand = None

    def true_geometry(self) -> CameraGeometry:
        return CameraGeometry(self.H, (self.w, self.h))

    def project(self, p3):
        p = np.atleast_2d(np.asarray(p3, float))
        ph = np.c_[p, np.ones(len(p))] @ self.P.T
        return ph[:, :2] / ph[:, 2:3]

    def add_dart(self, x, y, tilt=(0.0, 0.0), seed=None):
        """Dart tip at board (x, y); tilt = small (dx, dy) of the axis per mm."""
        self.darts.append((x, y, tilt))

    def clear(self):
        self.darts.clear()

    def _draw_dart(self, img, x, y, tilt):
        d = np.array([tilt[0], tilt[1], 1.0])
        d /= np.linalg.norm(d)
        tip = np.array([x, y, 0.0])
        # (start mm, end mm, radius mm, colour)
        # steel point: tapered cone ending exactly at the tip
        side = np.cross(d, self.R[2])  # perpendicular to the view ray
        if np.linalg.norm(side) < 1e-6:
            side = np.array([1.0, 0, 0])
        side /= np.linalg.norm(side)
        cone = [tip, tip + d * 30 + side * 1.1, tip + d * 30 - side * 1.1]
        pts = np.round(self.project(cone) * 16).astype(np.int32)
        cv2.fillPoly(img, [pts], (150, 150, 155), cv2.LINE_AA, shift=4)
        parts = [(30, 75, 3.4, (95, 100, 110)),     # barrel
                 (75, 110, 2.2, (30, 30, 30)),      # shaft
                 ]
        for s0, s1, rad, col in parts:
            a = self.project(tip + d * s0)[0]
            b = self.project(tip + d * s1)[0]
            mid = tip + d * (s0 + s1) / 2
            # pixel thickness from projected radius
            ref = self.project(mid)[0]
            off = np.cross(d, [0, 0, 1.0])
            if np.linalg.norm(off) < 1e-6:
                off = np.array([1.0, 0, 0])
            off /= np.linalg.norm(off)
            # thickness ~ f*rad/depth
            depth = (self.R @ mid + self.t)[2]
            th = max(1, int(round(2 * rad * self.K[0, 0] / depth)))
            cv2.line(img, tuple(np.round(a * 16).astype(int)),
                     tuple(np.round(b * 16).astype(int)), col, th,
                     cv2.LINE_AA, shift=4)
        # flight: two crossed quads
        for ang in (0, math.pi / 2):
            u = np.array([math.cos(ang), math.sin(ang), 0.0])
            u = u - d * (u @ d)
            u /= np.linalg.norm(u)
            quad = [tip + d * 105, tip + d * 105 + u * 16, tip + d * 145 + u * 16,
                    tip + d * 145 - u * 16, tip + d * 105 - u * 16]
            pts = np.round(self.project(quad) * 16).astype(np.int32)
            cv2.fillPoly(img, [pts], (40, 40, 180), cv2.LINE_AA, shift=4)

    def render(self, light=1.0) -> np.ndarray:
        img = self._base.copy()
        for x, y, tilt in self.darts:
            self._draw_dart(img, x, y, tilt)
        if self.hand is not None:
            cx, cy = self.hand
            c = self.project([cx, cy, 60.0])[0]
            cv2.circle(img, tuple(int(v) for v in c), self.w // 5, (120, 150, 200), -1)
        if light != 1.0:
            img = cv2.convertScaleAbs(img, alpha=light)
        if self.noise:
            n = self.rng.normal(0, self.noise, img.shape).astype(np.int16)
            img = np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)
        return img


def default_rig(size=(640, 480), noise=2.0, seed=0) -> list[SimCamera]:
    """Three cameras at 120 deg spacing (like a typical light-ring setup)."""
    return [SimCamera(a, size=size, noise=noise, seed=seed + i)
            for i, a in enumerate((90.0, 210.0, 330.0))]


def random_throw(rng: np.random.Generator):
    """Random dart position on the board (area-uniform) and axis tilt."""
    r = B.R_DOUBLE_OUT * 1.02 * math.sqrt(rng.random())
    a = rng.random() * 360
    x, y = B.polar(r, a)
    tilt = tuple(rng.normal(0, 0.15, 2))
    return x, y, tilt
