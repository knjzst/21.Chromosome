"""Camera geometry derived from a single board-plane homography.

Every camera is calibrated with 4+ clicked board points, which gives a
homography H (board mm -> image px).  From H plus a principal-point guess
we recover focal length and the full camera pose.  The pose is used for

* mapping a dart tip pixel to board coordinates (exact for the tip, since the
  tip lies on the board plane),
* predicting in which image direction a dart's barrel/flight points, so we
  know which end of a detected blob is the tip,
* estimating the per-camera position uncertainty (covariance), which drives
  the multi-camera fusion.
"""
from __future__ import annotations

import math

import numpy as np


def homography_dlt(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Normalised DLT homography (src -> dst), N >= 4 points."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)

    def norm(p):
        c = p.mean(0)
        s = math.sqrt(2) / max(np.sqrt(((p - c) ** 2).sum(1)).mean(), 1e-9)
        T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
        ph = np.c_[p, np.ones(len(p))] @ T.T
        return ph, T

    a, Ta = norm(src)
    b, Tb = norm(dst)
    rows = []
    for (x, y, _), (u, v, _) in zip(a, b):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.array(rows))
    Hn = vt[-1].reshape(3, 3)
    H = np.linalg.inv(Tb) @ Hn @ Ta
    return H / H[2, 2]


def apply_h(H: np.ndarray, pts) -> np.ndarray:
    p = np.atleast_2d(np.asarray(pts, float))
    ph = np.c_[p, np.ones(len(p))] @ H.T
    return ph[:, :2] / ph[:, 2:3]


class CameraGeometry:
    def __init__(self, H: np.ndarray, image_size: tuple[int, int],
                 fov_deg: float | None = None):
        self.H = np.asarray(H, float)
        self.Hinv = np.linalg.inv(self.H)
        self.w, self.h = image_size
        cx, cy = self.w / 2.0, self.h / 2.0
        f = self._focal_from_h(cx, cy)
        if f is None or not (0.2 * self.w < f < 5 * self.w):
            fov = math.radians(fov_deg or 90.0)
            f = (self.w / 2.0) / math.tan(fov / 2)
        self.f = f
        self.K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
        self._decompose()

    # -- intrinsics / pose -------------------------------------------------
    def _focal_from_h(self, cx, cy):
        T = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]])
        Hc = T @ self.H
        h1, h2 = Hc[:, 0], Hc[:, 1]
        # omega = diag(1/f^2, 1/f^2, 1); constraints from orthonormal r1, r2
        # (a) h1' w h2 = 0      (b) h1' w h1 - h2' w h2 = 0
        a_num = -(h1[2] * h2[2])
        a_den = h1[0] * h2[0] + h1[1] * h2[1]
        b_num = -(h1[2] ** 2 - h2[2] ** 2)
        b_den = (h1[0] ** 2 + h1[1] ** 2) - (h2[0] ** 2 + h2[1] ** 2)
        # least squares for k = 1/f^2:  a_den*k = a_num, b_den*k = b_num
        den = a_den ** 2 + b_den ** 2
        if den < 1e-18:
            return None
        k = (a_den * a_num + b_den * b_num) / den
        if k <= 0:
            return None
        return 1.0 / math.sqrt(k)

    def _decompose(self):
        M = np.linalg.inv(self.K) @ self.H
        lam = 1.0 / np.linalg.norm(M[:, 0])
        if M[2, 2] * lam < 0:  # board must be in front of the camera
            lam = -lam
        r1 = M[:, 0] * lam
        r2 = M[:, 1] * lam
        t = M[:, 2] * lam
        r3 = np.cross(r1, r2)
        R = np.c_[r1, r2, r3]
        u, _, vt = np.linalg.svd(R)  # orthonormalise
        R = u @ vt
        self.R, self.t = R, t
        self.center = -R.T @ t  # camera centre in board coords
        self.P = self.K @ np.c_[R, t]

    # -- mapping ----------------------------------------------------------
    def project(self, pts3d) -> np.ndarray:
        p = np.atleast_2d(np.asarray(pts3d, float))
        ph = np.c_[p, np.ones(len(p))] @ self.P.T
        return ph[:, :2] / ph[:, 2:3]

    def board_to_image(self, pts) -> np.ndarray:
        return apply_h(self.H, pts)

    def image_to_board(self, pts) -> np.ndarray:
        return apply_h(self.Hinv, pts)

    def dart_direction(self, board_xy, length_mm: float = 40.0) -> np.ndarray:
        """Unit image vector from the tip towards the barrel for a dart that
        sticks straight out of the board at board_xy."""
        x, y = board_xy
        a, b = self.project([[x, y, 0.0], [x, y, length_mm]])
        d = b - a
        n = np.linalg.norm(d)
        return d / n if n > 1e-9 else np.array([0.0, -1.0])

    def board_covariance(self, board_xy, pixel_sigma: float = 1.0) -> np.ndarray:
        """2x2 covariance (mm^2) of a board point given isotropic pixel noise."""
        x, y = board_xy
        e = 0.5
        p0 = self.board_to_image([x, y])[0]
        px = self.board_to_image([x + e, y])[0]
        py = self.board_to_image([x, y + e])[0]
        J = np.c_[(px - p0) / e, (py - p0) / e]  # d(img)/d(board), 2x2
        JtJ = J.T @ J + 1e-9 * np.eye(2)
        return pixel_sigma ** 2 * np.linalg.inv(JtJ)

    def to_dict(self) -> dict:
        return {"H": self.H.tolist(), "image_size": [self.w, self.h],
                "focal": self.f}
