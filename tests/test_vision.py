import numpy as np

from lowdarts import board as B
from lowdarts import calibration
from lowdarts.camera import SimSource
from lowdarts.engine import Engine
from lowdarts.evaluate import run
from lowdarts.geometry import CameraGeometry, homography_dlt
from lowdarts.sim import default_rig


def test_homography_and_focal_recovery():
    cam = default_rig()[1]
    g = CameraGeometry(cam.H, (cam.w, cam.h))
    assert abs(g.f - cam.K[0, 0]) < 1.0
    bp = np.array(B.calibration_points())
    ip = cam.project(np.c_[bp, np.zeros(4)])
    H = homography_dlt(bp, ip)
    back = CameraGeometry(H, (cam.w, cam.h)).image_to_board(ip)
    assert np.abs(back - bp).max() < 1e-6


def test_calibration_refine_fixes_sloppy_clicks():
    rng = np.random.default_rng(5)
    cam = default_rig()[0]
    bp = np.array(B.calibration_points())
    ip = cam.project(np.c_[bp, np.zeros(4)]) + rng.normal(0, 3, (4, 2))
    g, score = calibration.refine(cam.render(), calibration.from_clicks(ip, (cam.w, cam.h)), levels=3)
    grid = np.array([B.polar(r, a) for r in (30, 100, 165) for a in range(0, 360, 45)])
    true = cam.project(np.c_[grid, np.zeros(len(grid))])
    assert score > 0.9
    assert np.linalg.norm(g.board_to_image(grid) - true, axis=1).mean() < 0.3


def test_end_to_end_accuracy():
    r = run(throws=60, seed=7)
    assert r["detected"] == 1.0
    assert r["err_mean_mm"] < 0.8
    assert r["score_accuracy"] >= 0.93


def test_engine_dart_and_takeout_cycle():
    rig = default_rig()
    srcs = [SimSource(c) for c in rig]
    events = []
    eng = Engine(srcs, [c.true_geometry() for c in rig], events.append)

    def act(fn):
        for c, s in zip(rig, srcs):
            fn(c)
            s.invalidate()
        for _ in range(5):
            eng.tick()

    act(lambda c: None)
    act(lambda c: c.add_dart(0, 103))
    act(lambda c: c.add_dart(-30, -160))
    act(lambda c: setattr(c, "hand", (0, 50)))     # hand in front
    act(lambda c: c.clear())                        # pulls darts, hand still there
    act(lambda c: setattr(c, "hand", None))         # hand gone
    act(lambda c: c.add_dart(50, -20))
    kinds = [(e.kind, e.hit.label if e.hit else e.info) for e in events]
    assert kinds == [("dart", "T20"), ("dart", "D19"), ("status", "occluded"),
                     ("status", "occluded"), ("takeout", ""), ("dart", "S10")]
