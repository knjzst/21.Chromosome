"""Spitzen-Erkennung auf dem Crop – klassische Geometrie, NN-frei (v0).

Autodarts-Prinzipien 2+3: Analysiert wird nur ein Crop um die Änderungsregion
("each cell shows the whole dart and no background around it"), und zwar zuerst
mit klassischer CV: Differenzmaske -> Schaftlinie (Hough) -> Spitze = Endpunkt
der Linie Richtung Board. Ein Keypoint-NN kann später als Verfeinerung an
genau dieser Stelle eingehängt werden (gleiche Signatur, Crop rein, Punkt raus).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import Config


@dataclass
class TipDetection:
    tip_px: tuple[float, float]      # Spitze im Vollbild (px)
    confidence: float                # 0..1 heuristisch
    crop_box: tuple[int, int, int, int]
    debug_crop: np.ndarray | None = None


def _clamp_box(x: int, y: int, w: int, h: int, size: int,
               img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """Quadratischen Crop der Kantenlänge >= size um die Box legen, im Bild halten."""
    cx, cy = x + w // 2, y + h // 2
    half = max(size, max(w, h)) // 2 + 8
    x0 = max(0, min(cx - half, img_w - 2 * half))
    y0 = max(0, min(cy - half, img_h - 2 * half))
    return x0, y0, min(2 * half, img_w - x0), min(2 * half, img_h - y0)


def detect_tip(frame: np.ndarray, reference: np.ndarray,
               bbox: tuple[int, int, int, int], board_center_px: tuple[float, float],
               cfg: Config) -> TipDetection | None:
    """Dartspitze im Änderungsbereich finden.

    frame/reference: Vollbilder (BGR) nach/vor dem Wurf.
    bbox: Änderungs-Bounding-Box aus dem Motion-Detektor (Vollbild-px).
    board_center_px: Bull-Position im Bild (aus der Kalibrier-Ellipse) – die
    Spitze ist der Linien-Endpunkt, der dem Board-Zentrum näher liegt.
    """
    d = cfg.section("detect")
    size = int(cfg.get("processing.crop_size", 192))
    img_h, img_w = frame.shape[:2]
    x0, y0, w, h = _clamp_box(*bbox, size, img_w, img_h)

    cur = cv2.cvtColor(frame[y0:y0 + h, x0:x0 + w], cv2.COLOR_BGR2GRAY)
    ref = cv2.cvtColor(reference[y0:y0 + h, x0:x0 + w], cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(cv2.GaussianBlur(cur, (3, 3), 0), cv2.GaussianBlur(ref, (3, 3), 0))
    _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    # Schaftlinie im Differenzbereich suchen
    edges = cv2.Canny(cur, int(d["canny_low"]), int(d["canny_high"]))
    edges = cv2.bitwise_and(edges, mask)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180,
                            threshold=int(d["hough_threshold"]),
                            minLineLength=int(d["min_line_length"]),
                            maxLineGap=int(d["max_line_gap"]))

    cx_b, cy_b = board_center_px[0] - x0, board_center_px[1] - y0

    if lines is not None and len(lines):
        # Längste Linie = Schaft; Spitze = Endpunkt näher am Board-Zentrum
        best = max(lines[:, 0, :], key=lambda l: (l[0] - l[2]) ** 2 + (l[1] - l[3]) ** 2)
        p1, p2 = (best[0], best[1]), (best[2], best[3])
        tip_local = min((p1, p2), key=lambda p: (p[0] - cx_b) ** 2 + (p[1] - cy_b) ** 2)
        length = float(np.hypot(best[0] - best[2], best[1] - best[3]))
        conf = min(1.0, length / (1.5 * int(d["min_line_length"])))
    else:
        # Fallback: Maskenpunkt, der dem Board-Zentrum am nächsten liegt
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return None
        idx = np.argmin((xs - cx_b) ** 2 + (ys - cy_b) ** 2)
        tip_local = (float(xs[idx]), float(ys[idx]))
        conf = 0.3

    return TipDetection(
        tip_px=(x0 + float(tip_local[0]), y0 + float(tip_local[1])),
        confidence=conf,
        crop_box=(x0, y0, w, h),
        debug_crop=frame[y0:y0 + h, x0:x0 + w].copy(),
    )
