"""Event-driven detection loop.

Nothing heavy runs while the board is quiet: each tick only compares tiny
(1/4 or 1/8 scale) grayscale frames.  The expensive full-resolution analysis
runs once per dart, after the image has settled.

States
    IDLE    -> motion in any camera                -> MOVING
    MOVING  -> all cameras stable for N ticks      -> analyse:
               small change (dart sized)           -> DART event
               big change, board ~ empty reference -> TAKEOUT event
               big change otherwise                -> wait (hand / person in view)
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import board as B
from .detector import find_tip, roi_mask
from .fusion import fuse
from .geometry import CameraGeometry

log = logging.getLogger("lowdarts")


@dataclass
class EngineConfig:
    fps: float = 10.0
    motion_thresh: int = 18        # grey-level difference (small frames)
    motion_frac: float = 0.0015    # fraction of ROI pixels that must change
    settle_ticks: int = 3          # stable ticks before analysing
    dart_max_frac: float = 0.12    # change bigger than this -> not a single dart
    takeout_empty_frac: float = 0.002  # "board looks empty" (1 dart ~ 0.003-0.01)
    diff_thresh: int = 22          # full-res change threshold for tip finding
    pixel_sigma: float = 1.0


@dataclass
class Event:
    kind: str                       # "dart" | "takeout" | "status"
    hit: B.Hit | None = None
    cams: list[int] = field(default_factory=list)
    tips: list = field(default_factory=list)
    info: str = ""
    confident: bool = True          # False -> UI asks the player to check


class Engine:
    def __init__(self, sources, geoms: list[CameraGeometry], on_event=None,
                 cfg: EngineConfig | None = None):
        self.sources = sources
        self.geoms = geoms
        self.cfg = cfg or EngineConfig()
        self.on_event = on_event or (lambda e: None)
        self.rois = [roi_mask(g) for g in geoms]
        self.small_rois = []
        self.ref = [None] * len(sources)        # full frames before the dart
        self.empty_ref = [None] * len(sources)  # small frames, board w/o darts
        self.prev_small = [None] * len(sources)
        self.last_seq = [-1] * len(sources)
        self.moving = False
        self.stable = 0
        self.darts_on_board = 0
        self.state = "init"
        self.stats = {"ticks": 0, "analyses": 0, "busy_s": 0.0}
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------
    def _small_roi(self, i, shape):
        while len(self.small_rois) <= i:
            self.small_rois.append(None)
        r = self.small_rois[i]
        if r is None or r.shape != shape:
            r = cv2.resize(self.rois[i], (shape[1], shape[0]),
                           interpolation=cv2.INTER_NEAREST)
            self.small_rois[i] = r
        return r

    def _frac(self, a, b, roi):
        d = cv2.absdiff(a, b)
        n = cv2.countNonZero(cv2.bitwise_and(
            cv2.threshold(d, self.cfg.motion_thresh, 255, cv2.THRESH_BINARY)[1], roi))
        return n / max(cv2.countNonZero(roi), 1)

    def reset_reference(self):
        """Take current images as 'empty board' reference."""
        for i, s in enumerate(self.sources):
            _, fr = s.latest()
            if fr is None:
                continue
            self.ref[i] = fr.full()
            self.empty_ref[i] = fr.small()
            self.prev_small[i] = fr.small()
        self.darts_on_board = 0
        self.state = "idle"

    # ------------------------------------------------------------------
    def tick(self) -> list[Event]:
        """Process the newest frames once. Returns the events emitted."""
        t0 = time.perf_counter()
        self.stats["ticks"] += 1
        frames, motion = [], 0.0
        for i, s in enumerate(self.sources):
            seq, fr = s.latest()
            frames.append(fr)
            if fr is None:
                continue
            sm = fr.small()
            if self.prev_small[i] is None or self.prev_small[i].shape != sm.shape:
                self.prev_small[i] = sm
                continue
            roi = self._small_roi(i, sm.shape)
            motion = max(motion, self._frac(sm, self.prev_small[i], roi))
            self.prev_small[i] = sm
        events = []
        if any(r is None for r in self.ref):
            self.reset_reference()
        elif motion > self.cfg.motion_frac:
            self.moving, self.stable = True, 0
            self.state = "motion"
        elif self.moving:
            self.stable += 1
            if self.stable >= self.cfg.settle_ticks:
                self.moving = False
                events = self._analyse(frames)
                self.state = "idle"
        self.stats["busy_s"] += time.perf_counter() - t0
        for e in events:
            self.on_event(e)
        return events

    def _analyse(self, frames) -> list[Event]:
        self.stats["analyses"] += 1
        cfg = self.cfg
        # how much changed vs. last reference / vs. empty board (cheap, small)
        ch, empty = [], []
        for i, fr in enumerate(frames):
            sm = fr.small()
            roi = self._small_roi(i, sm.shape)
            ref_small = cv2.resize(cv2.cvtColor(self.ref[i], cv2.COLOR_BGR2GRAY),
                                   (sm.shape[1], sm.shape[0]),
                                   interpolation=cv2.INTER_AREA)
            ch.append(self._frac(sm, ref_small, roi))
            empty.append(self._frac(sm, self.empty_ref[i], roi))
        log.debug("analyse change=%s empty=%s", np.round(ch, 4), np.round(empty, 4))

        if max(ch) < cfg.motion_frac:
            return []  # nothing new (e.g. motion outside / flicker)

        looks_empty = sum(e < cfg.takeout_empty_frac for e in empty) >= 2
        if self.darts_on_board and looks_empty:
            for i, fr in enumerate(frames):
                self.ref[i] = fr.full()
                self.empty_ref[i] = fr.small()
            self.darts_on_board = 0
            return [Event("takeout")]
        if sum(c > cfg.dart_max_frac for c in ch) >= 2:
            # hand / person in front of the board – wait for the next settle
            return [Event("status", info="occluded")]

        results = []
        for i, fr in enumerate(frames):
            cur = fr.full()
            try:
                r = find_tip(self.ref[i], cur, self.geoms[i], self.rois[i],
                             thresh=cfg.diff_thresh, pixel_sigma=cfg.pixel_sigma)
            except Exception:  # noqa: BLE001 – a bad frame must not kill the loop
                log.exception("tip detection failed on camera %d", i)
                r = None
            results.append(r)
        for i, fr in enumerate(frames):
            self.ref[i] = fr.full()
        f = fuse(results)
        if f is None:
            return [Event("status", info="no dart found")]
        xy, cov, used = f
        hit = B.score_point(float(xy[0]), float(xy[1]))
        self.darts_on_board += 1
        return [Event("dart", hit=hit, cams=used, confident=len(used) >= 2,
                      tips=[None if r is None else r.tip.tolist() for r in results],
                      info=f"sd={np.sqrt(np.trace(cov)):.2f}mm")]

    # ------------------------------------------------------------------
    def run_forever(self):
        period = 1.0 / self.cfg.fps
        while not self._stop.is_set():
            t = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("engine tick failed")
            time.sleep(max(0.0, period - (time.monotonic() - t)))

    def start(self):
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
