"""CPU / USB budget benchmark (simulated frames, single core).

Compares the LowDarts idle loop with an "always decode full frames at
30 FPS" pipeline (what a typical continuous-processing setup must at least do
*before* any neural network runs).
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from .camera import Frame
from .detector import find_tip, roi_mask
from .fusion import fuse
from .sim import default_rig


def _time(fn, seconds=1.0):
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        fn()
        n += 1
    return (time.perf_counter() - t0) / n


def main(a=None):
    cv2.setNumThreads(1)
    res = getattr(a, "res", "640x480")
    secs = max(getattr(a, "seconds", 5) / 5, 0.3)
    w, h = map(int, res.split("x"))
    rig = default_rig(size=(w, h))
    imgs = [c.render() for c in rig]
    jpgs = [cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes() for im in imgs]
    geoms = [c.true_geometry() for c in rig]
    rois = [roi_mask(g) for g in geoms]

    # full decode (baseline per frame)
    t_full = _time(lambda: cv2.imdecode(np.frombuffer(jpgs[0], np.uint8), cv2.IMREAD_COLOR), secs)

    # lowdarts idle tick per camera: reduced decode + diff + count in ROI
    small_roi = cv2.resize(rois[0], (w // 4, h // 4), interpolation=cv2.INTER_NEAREST)
    prev = Frame(jpeg=jpgs[0], scale=4).small()

    def idle():
        s = Frame(jpeg=jpgs[0], scale=4).small()
        d = cv2.absdiff(s, prev)
        _, m = cv2.threshold(d, 18, 255, cv2.THRESH_BINARY)
        cv2.countNonZero(cv2.bitwise_and(m, small_roi))
    t_idle = _time(idle, secs)

    # one dart analysis (3 cams, full decode + tip + fusion)
    refs = imgs
    for c in rig:
        c.add_dart(20, 60, (0.1, 0.0))
    curs = [cv2.imencode(".jpg", c.render(), [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes() for c in rig]

    def dart():
        res_ = []
        for r, cj, g, roi in zip(refs, curs, geoms, rois):
            cu = cv2.imdecode(np.frombuffer(cj, np.uint8), cv2.IMREAD_COLOR)
            res_.append(find_tip(r, cu, g, roi))
        fuse(res_)
    t_dart = _time(dart, secs)

    jpg_kb = np.mean([len(j) for j in jpgs]) / 1024
    yuyv_kb = w * h * 2 / 1024
    base_fps, low_fps, cams = 30, 10, 3
    base_cpu = t_full * base_fps * cams * 100
    low_cpu = t_idle * low_fps * cams * 100
    print(f"Aufloesung {w}x{h}, {cams} Kameras, 1 CPU-Kern dieses Rechners")
    print(f"  Voll-Dekodierung pro Frame          {t_full*1000:7.2f} ms")
    print(f"  LowDarts Idle-Tick pro Kamera       {t_idle*1000:7.2f} ms")
    print(f"  LowDarts Analyse pro Dart (3 Kams)  {t_dart*1000:7.2f} ms")
    print(f"CPU-Last (Anteil eines Kerns):")
    print(f"  Basis: 30 FPS voll dekodieren (ohne NN!) {base_cpu:6.1f} %")
    print(f"  LowDarts: 10 FPS Idle                    {low_cpu:6.1f} %   "
          f"(+{t_dart*1000:.0f} ms einmal pro Dart)")
    print(f"USB-Bandbreite gesamt:")
    print(f"  YUYV  30 FPS: {yuyv_kb*30*cams/1024:6.1f} MB/s   (USB 2.0 real ~35 MB/s)")
    print(f"  MJPEG 30 FPS: {jpg_kb*30*cams/1024:6.1f} MB/s")
    print(f"  MJPEG 10 FPS: {jpg_kb*10*cams/1024:6.1f} MB/s   <- LowDarts")
    return {"t_full": t_full, "t_idle": t_idle, "t_dart": t_dart,
            "base_cpu": base_cpu, "low_cpu": low_cpu}


if __name__ == "__main__":
    main()
