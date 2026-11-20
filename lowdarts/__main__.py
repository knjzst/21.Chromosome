"""LowDarts command line.

    python -m lowdarts run --cams 0 2 4          # real cameras
    python -m lowdarts demo                      # simulated board, no hardware
    python -m lowdarts evaluate --throws 300     # accuracy on the simulator
    python -m lowdarts bench                     # CPU cost per tick / per dart
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import threading
import time
from pathlib import Path

import cv2

from . import calibration
from .camera import Camera, SimSource
from .engine import Engine, EngineConfig
from .server import App, serve
from .sim import default_rig, random_throw

log = logging.getLogger("lowdarts")


def _lean_opencv():
    # one worker thread is plenty for our tiny images and avoids thread
    # pool overhead/contention on small CPUs
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)


def cmd_run(a):
    w, h = map(int, a.res.split("x"))
    sources = [Camera(c, (w, h), a.fps, a.scale).start() for c in a.cams]
    time.sleep(1.0)
    if Path(a.calib).exists():
        geoms, _ = calibration.load(a.calib)
        if len(geoms) != len(sources):
            log.warning("calibration has %d cameras, %d given", len(geoms), len(sources))
    else:
        log.warning("no %s – open /setup in the browser to calibrate", a.calib)
        geoms = [c.true_geometry() for c in default_rig(size=(w, h))][:len(sources)]
    app = App(sources=sources, calib_path=a.calib)
    eng = Engine(sources, geoms, app.on_event, EngineConfig(fps=a.fps))
    app.engine = eng
    eng.start()
    serve(app, a.host, a.port)


def cmd_demo(a):
    """Simulated board: random darts every few seconds, auto takeout."""
    rig = default_rig()
    sources = [SimSource(c) for c in rig]
    app = App(sources=sources, calib_path=os.devnull)
    geoms = []
    rng = __import__("numpy").random.default_rng(0)
    from .evaluate import calibrate_sim
    for c in rig:
        geoms.append(calibrate_sim(c, rng, click_px=2.0))
    eng = Engine(sources, geoms, app.on_event, EngineConfig(fps=a.fps))
    app.engine = eng
    eng.start()

    def thrower():
        n = 0
        while True:
            time.sleep(a.interval)
            if n == 3:
                for c, s in zip(rig, sources):
                    c.clear()
                    s.invalidate()
                n = 0
                continue
            x, y, tilt = random_throw(rng)
            if random.random() < 0.5:  # aim-ish at the treble 20 area
                x, y = random.gauss(0, 12), random.gauss(103, 10)
            for c, s in zip(rig, sources):
                c.add_dart(x, y, tilt)
                s.invalidate()
            n += 1

    threading.Thread(target=thrower, daemon=True).start()
    serve(app, a.host, a.port)


def cmd_evaluate(a):
    from .evaluate import run
    w, h = map(int, a.res.split("x"))
    r = run(a.throws, (w, h), a.click_px, seed=a.seed)
    for k, v in r.items():
        print(f"{k:22s} {v:.4f}" if isinstance(v, float) else f"{k:22s} {v}")


def cmd_bench(a):
    from .bench import main as bench_main
    bench_main(a)


def main():
    ap = argparse.ArgumentParser(prog="lowdarts")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run with real USB cameras")
    r.add_argument("--cams", nargs="+", default=["0", "2", "4"],
                   help="camera indices or device paths (/dev/video0 ...)")
    r.add_argument("--res", default="640x480")
    r.add_argument("--fps", type=float, default=10)
    r.add_argument("--scale", type=int, default=4, choices=[2, 4, 8],
                   help="downscale factor for motion detection")
    r.add_argument("--calib", default="calibration.json")
    r.add_argument("--host", default="0.0.0.0")
    r.add_argument("--port", type=int, default=8080)
    r.set_defaults(fn=cmd_run)

    d = sub.add_parser("demo", help="simulated board, no hardware needed")
    d.add_argument("--fps", type=float, default=10)
    d.add_argument("--interval", type=float, default=2.5)
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8080)
    d.set_defaults(fn=cmd_demo)

    e = sub.add_parser("evaluate", help="accuracy on the simulator")
    e.add_argument("--throws", type=int, default=300)
    e.add_argument("--res", default="640x480")
    e.add_argument("--click-px", type=float, default=2.0)
    e.add_argument("--seed", type=int, default=1)
    e.set_defaults(fn=cmd_evaluate)

    b = sub.add_parser("bench", help="CPU cost per idle tick / per dart")
    b.add_argument("--res", default="640x480")
    b.add_argument("--seconds", type=float, default=5)
    b.set_defaults(fn=cmd_bench)

    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    _lean_opencv()
    a.fn(a)


if __name__ == "__main__":
    main()
