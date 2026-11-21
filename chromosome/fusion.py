"""Multi-Kamera-Fusion: Lesungen aller Kameras in Board-Koordinaten zusammenführen.

Autodarts-Prinzip 5: "The yellow segment is that one camera's read, not the
final score." – jede Kamera liefert einen Boardpunkt, die Fusion bildet daraus
den endgültigen Treffpunkt: Ausreißer per Median-Abstand verwerfen, Rest
konfidenzgewichtet mitteln. Bewusst ohne 3D-Triangulation – für steckende
Darts auf der Board-Ebene reicht die 2D-Fusion und spart Rechenzeit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config


@dataclass
class CameraRead:
    cam_no: int
    x_mm: float
    y_mm: float
    confidence: float


@dataclass
class FusedPoint:
    x_mm: float
    y_mm: float
    used: list[int]        # Kameranummern, die eingegangen sind
    rejected: list[int]    # Ausreißer
    spread_mm: float       # max. Abstand der genutzten Lesungen zum Ergebnis


def fuse(reads: list[CameraRead], cfg: Config) -> FusedPoint | None:
    f = cfg.section("fusion")
    min_cams = int(f.get("min_cameras", 2))
    max_res = float(f.get("max_residual_mm", 6.0))

    reads = [r for r in reads if r.confidence >= float(cfg.get("detect.dart_confidence", 0.5))]
    if len(reads) < max(1, min_cams):
        return None

    pts = np.array([[r.x_mm, r.y_mm] for r in reads])
    med = np.median(pts, axis=0)
    dist = np.linalg.norm(pts - med, axis=1)
    keep = dist <= max_res
    if keep.sum() < max(1, min_cams):
        # Alle streuen stark: die zwei nächstbeieinanderliegenden behalten
        order = np.argsort(dist)
        keep = np.zeros(len(reads), dtype=bool)
        keep[order[:max(1, min_cams)]] = True

    w = np.array([reads[i].confidence for i in range(len(reads))])[keep]
    sel = pts[keep]
    fused = (sel * w[:, None]).sum(axis=0) / w.sum()
    spread = float(np.linalg.norm(sel - fused, axis=1).max())

    return FusedPoint(
        x_mm=float(fused[0]),
        y_mm=float(fused[1]),
        used=[reads[i].cam_no for i in range(len(reads)) if keep[i]],
        rejected=[reads[i].cam_no for i in range(len(reads)) if not keep[i]],
        spread_mm=spread,
    )
