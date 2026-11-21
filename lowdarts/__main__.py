"""LowDarts command line.

    python -m lowdarts                 # desktop app (window), same as `app`
    python -m lowdarts app             # desktop window (pywebview / browser fallback)
    python -m lowdarts serve           # server only, open in any browser
    python -m lowdarts demo            # simulated board with cameras, no hardware
    python -m lowdarts evaluate        # detection accuracy on the simulator
    python -m lowdarts bench           # CPU cost per idle tick / per dart
"""
from __future__ import annotations

import argparse
import logging
import random
import tempfile
import threading
import time
from pathlib import Path

import cv2

log = logging.getLogger("lowdarts")


def _lean_opencv():
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)


def _make_app(a):
    from .server import App
    app = App(Path(a.data) if getattr(a, "data", None) else None)
    cams = getattr(a, "cams", None) or (app.settings["cameras"] if getattr(a, "autostart", True) else [])
    if cams:
        try:
            app.start_cameras([str(c) for c in cams])
        except ValueError as e:
            log.warning("Kameras nicht gestartet: %s", e)
    return app


def cmd_serve(a):
    from .server import serve
    serve(_make_app(a), a.host, a.port)


def cmd_app(a):
    from .desktop import run_desktop
    run_desktop(_make_app(a), fullscreen=a.fullscreen)


def cmd_demo(a):
    """Simulated board: 3 virtual cameras, random darts, auto takeout."""
    import numpy as np
    from .camera import SimSource
    from .engine import Engine, EngineConfig
    from .evaluate import calibrate_sim
    from .server import App, serve
    from .sim import default_rig, random_throw

    rig = default_rig()
    sources = [SimSource(c) for c in rig]
    app = App(Path(a.data) if a.data else Path(tempfile.mkdtemp(prefix="lowdarts-demo-")))
    rng = np.random.default_rng(0)
    geoms = [calibrate_sim(c, rng, click_px=2.0) for c in rig]
    app.sources = sources
    app._cal_flags = [True] * 3
    app.engine = Engine(sources, geoms, app.on_event, EngineConfig(fps=a.fps))
    app.engine.start()

    def thrower():
        n = 0
        while True:
            time.sleep(a.interval)
            if app.game.finished or app.game.current in app.bots:
                continue
            if n >= 3 or app.game.turn_done:
                for c, s in zip(rig, sources):
                    c.clear()
                    s.invalidate()
                n = 0
                continue
            x, y, tilt = random_throw(rng)
            if random.random() < 0.6:
                x, y = random.gauss(0, 12), random.gauss(103, 10)
            for c, s in zip(rig, sources):
                c.add_dart(x, y, tilt)
                s.invalidate()
            n += 1

    threading.Thread(target=thrower, daemon=True).start()
    if a.window:
        from .desktop import run_desktop
        run_desktop(app)
    else:
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lowdarts")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--data", help="Datenordner (Standard: %%APPDATA%%\\LowDarts)")
        p.add_argument("--cams", nargs="*", help="Kamera-Indizes oder Stream-URLs (überschreibt Einstellungen)")

    p = sub.add_parser("app", help="Desktop-Fenster")
    common(p)
    p.add_argument("--fullscreen", action="store_true")
    p.set_defaults(fn=cmd_app)

    p = sub.add_parser("serve", help="nur Server, Bedienung im Browser")
    common(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(fn=cmd_serve)

    d = sub.add_parser("demo", help="simuliertes Board mit Kameras")
    d.add_argument("--data")
    d.add_argument("--fps", type=float, default=10)
    d.add_argument("--interval", type=float, default=2.5)
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8080)
    d.add_argument("--window", action="store_true", help="im Desktop-Fenster statt Browser")
    d.set_defaults(fn=cmd_demo)

    e = sub.add_parser("evaluate", help="Erkennungs-Genauigkeit im Simulator")
    e.add_argument("--throws", type=int, default=300)
    e.add_argument("--res", default="640x480")
    e.add_argument("--click-px", type=float, default=2.0)
    e.add_argument("--seed", type=int, default=1)
    e.set_defaults(fn=cmd_evaluate)

    b = sub.add_parser("bench", help="CPU-Last")
    b.add_argument("--res", default="640x480")
    b.add_argument("--seconds", type=float, default=5)
    b.set_defaults(fn=cmd_bench)

    a = ap.parse_args(argv)
    if a.cmd is None:  # double-click on the .exe
        a = ap.parse_args(["app"] + (argv or []))
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    _lean_opencv()
    a.fn(a)


if __name__ == "__main__":
    main()
