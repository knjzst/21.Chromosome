"""Accuracy + speed evaluation on the synthetic rig.

    python -m lowdarts.evaluate --throws 300 --res 640x480
"""
from __future__ import annotations

import argparse
import math
import time

import numpy as np

from . import board as B
from . import calibration
from .detector import find_tip, roi_mask
from .fusion import fuse
from .geometry import CameraGeometry, homography_dlt
from .sim import default_rig, random_throw


def calibrate_sim(cam, rng, click_px=1.0, refine=True) -> CameraGeometry:
    """Simulate a user clicking the calibration points (with click error)."""
    bp = np.array(B.calibration_points())
    ip = cam.project(np.c_[bp, np.zeros(len(bp))])
    ip = ip + rng.normal(0, click_px, ip.shape)
    g = CameraGeometry(homography_dlt(bp, ip), (cam.w, cam.h))
    if refine:
        g, _ = calibration.refine(cam.render(), g, levels=3)
    return g


def run(throws=300, size=(640, 480), click_px=2.0, noise=2.0, seed=1,
        verbose=False, refine=True):
    rng = np.random.default_rng(seed)
    rig = default_rig(size=size, noise=noise, seed=seed)
    geoms = [calibrate_sim(c, rng, click_px, refine) for c in rig]
    rois = [roi_mask(g) for g in geoms]
    errs, correct, missed = [], 0, 0
    t_detect = 0.0
    refs = [c.render() for c in rig]
    for k in range(throws):
        if k % 3 == 0:  # new turn: darts pulled
            for c in rig:
                c.clear()
            refs = [c.render() for c in rig]
        x, y, tilt = random_throw(rng)
        for c in rig:
            c.add_dart(x, y, tilt)
        curs = [c.render() for c in rig]
        t0 = time.perf_counter()
        res = [find_tip(r, cu, g, roi) for r, cu, g, roi in zip(refs, curs, geoms, rois)]
        fused = fuse(res)
        t_detect += time.perf_counter() - t0
        refs = curs
        truth = B.score_point(x, y)
        if fused is None:
            missed += 1
            continue
        xy = fused[0]
        e = math.hypot(xy[0] - x, xy[1] - y)
        errs.append(e)
        got = B.score_point(*xy)
        ok = (got.sector, got.multiplier) == (truth.sector, truth.multiplier)
        correct += ok
        if verbose and not ok:
            print(f"  miss: true {truth.label} ({x:.1f},{y:.1f}) got {got.label} "
                  f"({xy[0]:.1f},{xy[1]:.1f}) err {e:.2f}mm cams={fused[2]}")
    errs = np.array(errs)
    return {
        "throws": throws,
        "score_accuracy": correct / throws,
        "detected": (throws - missed) / throws,
        "err_mean_mm": float(errs.mean()) if len(errs) else float("nan"),
        "err_p95_mm": float(np.percentile(errs, 95)) if len(errs) else float("nan"),
        "detect_ms_per_dart": 1000 * t_detect / throws,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--throws", type=int, default=300)
    ap.add_argument("--res", default="640x480")
    ap.add_argument("--click-px", type=float, default=2.0)
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--noise", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    w, h = map(int, a.res.split("x"))
    r = run(a.throws, (w, h), a.click_px, a.noise, a.seed, a.verbose,
            not a.no_refine)
    for k, v in r.items():
        print(f"{k:22s} {v:.4f}" if isinstance(v, float) else f"{k:22s} {v}")


if __name__ == "__main__":
    main()
