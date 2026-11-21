"""Kalibrierung: Ellipsen-Fit der Board-Ringe -> Homographie Bild -> Board-Ebene.

Autodarts-Prinzip 4: Die Scheibe ist im Kamerabild eine Ellipse (perspektivisch
verzerrter Kreis). Aus der äußeren Double-Ring-Ellipse + der 20er-Richtung wird
eine Homographie bestimmt, die Bildpunkte in Board-Millimeter (Ursprung = Bull,
y-Achse Richtung 20) abbildet. Einmal rechnen, dann cachen (calibration.json).

v0 bewusst halbautomatisch: Der Nutzer bestätigt/korrigiert die gefundene
Ellipse und markiert die 20. Vollautomatik kann später ergänzt werden.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from .config import Config


@dataclass
class CameraCalibration:
    homography: list[list[float]]        # 3x3, Bild-px -> Board-mm
    ellipse: tuple[float, float, float, float, float]  # cx, cy, w, h, angle (Double-Außenring)
    theta20: float                       # Winkel der 20er-Richtung im Bild (rad)

    def H(self) -> np.ndarray:
        return np.array(self.homography, dtype=np.float64)

    def image_to_board(self, pt: tuple[float, float]) -> tuple[float, float]:
        src = np.array([[pt]], dtype=np.float64)
        dst = cv2.perspectiveTransform(src, self.H())
        return float(dst[0, 0, 0]), float(dst[0, 0, 1])


def find_board_ellipse(frame: np.ndarray) -> tuple | None:
    """Größte plausible Ellipse im Bild suchen (Kandidat für den Double-Außenring)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, None, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    best, best_area = None, 0.0
    img_area = frame.shape[0] * frame.shape[1]
    for c in contours:
        if len(c) < 20:
            continue
        (cx, cy), (w, h), ang = cv2.fitEllipse(c)
        area = math.pi * (w / 2) * (h / 2)
        if area < 0.05 * img_area or area > 0.95 * img_area:
            continue
        if min(w, h) / max(w, h) < 0.45:      # zu flach -> keine Scheibe
            continue
        if area > best_area:
            best, best_area = (cx, cy, w, h, ang), area
    return best


def homography_from_ellipse(ellipse: tuple, theta20: float,
                            double_outer_r: float) -> np.ndarray:
    """Homographie aus 8 Punkten auf dem Double-Außenring + bekannter 20er-Richtung.

    Bildpunkte: 8 Punkte auf der Ellipse. Boardpunkte: dieselben 8 Winkel auf dem
    Kreis mit Radius double_outer_r, gedreht so, dass theta20 auf "oben" fällt.
    """
    cx, cy, w, h, ang = ellipse
    a, b = w / 2.0, h / 2.0
    phi = math.radians(ang)
    img_pts, brd_pts = [], []
    for k in range(8):
        t = 2 * math.pi * k / 8
        # Punkt auf der Bild-Ellipse (Parameterwinkel t)
        ex = a * math.cos(t)
        ey = b * math.sin(t)
        ix = cx + ex * math.cos(phi) - ey * math.sin(phi)
        iy = cy + ex * math.sin(phi) + ey * math.cos(phi)
        img_pts.append((ix, iy))
        # Zugehöriger Winkel im Bild, relativ zur 20er-Richtung
        alpha = math.atan2(iy - cy, ix - cx) - theta20
        # Board: x nach rechts, y nach OBEN (20 bei alpha=0 oben)
        bx = double_outer_r * math.sin(alpha)
        by = double_outer_r * math.cos(alpha)
        brd_pts.append((bx, by))
    H, _ = cv2.findHomography(np.array(img_pts), np.array(brd_pts), cv2.RANSAC, 3.0)
    return H


class CalibrationStore:
    """Kalibrierungen laden/speichern (eine je Kamera)."""

    def __init__(self, cfg: Config, path: Path | None = None) -> None:
        self._cfg = cfg
        self._path = path or Path("calibration.json")
        self.cams: dict[int, CameraCalibration] = {}
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        self.cams = {int(k): CameraCalibration(**v) for k, v in raw.items()}

    def save(self) -> None:
        raw = {str(k): asdict(v) for k, v in self.cams.items()}
        self._path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def calibrate_camera(self, cam_no: int, frame: np.ndarray,
                         theta20: float, ellipse: tuple | None = None) -> CameraCalibration | None:
        """Kalibrierung für eine Kamera berechnen.

        theta20: Winkel (rad) der Richtung Bull -> Mitte 20er-Segment im Bild,
        vom Nutzer über die API geliefert (Klick auf die 20 im Standbild).
        """
        ell = ellipse or find_board_ellipse(frame)
        if ell is None:
            return None
        H = homography_from_ellipse(ell, theta20, float(self._cfg.get("board.double_outer_r")))
        if H is None:
            return None
        calib = CameraCalibration(homography=H.tolist(), ellipse=tuple(ell), theta20=theta20)
        self.cams[cam_no] = calib
        self.save()
        return calib
