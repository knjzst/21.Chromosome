"""Engine: Orchestrierung Kameras -> Motion -> Detect -> Fusion -> Scoring.

Headless-Kern (Autodarts-Prinzip 8): läuft als Dienst ohne UI, die API
(api.py) ist der einzige Zugang. Ereignisse gehen als Event-Liste an
registrierte Listener (SSE in der API, Logging, Dumps).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .calibration import CalibrationStore
from .camera import CameraSet
from .config import Config
from .detect import detect_tip
from .fusion import CameraRead, FusedPoint, fuse
from .motion import MotionDetector, MotionState
from .scoring import Score, score_point

log = logging.getLogger("chromosome.engine")


@dataclass
class ThrowEvent:
    kind: str                       # "throw" | "takeout_started" | "takeout_finished" | "status"
    ts: float = field(default_factory=time.time)
    score: Score | None = None
    point: FusedPoint | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class Engine:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cameras = CameraSet(cfg)
        self.calib = CalibrationStore(cfg)
        self.detectors = [MotionDetector(cfg) for _ in self.cameras.sources]
        self._refs: list[np.ndarray | None] = [None] * len(self.cameras.sources)
        self._listeners: list[Callable[[ThrowEvent], None]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="engine")
        self.turn: list[Score] = []                   # Würfe seit letztem Takeout
        self.history: deque[ThrowEvent] = deque(maxlen=50)
        self._takeout_announced = False

    # -- Lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self.cameras.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.cameras.stop()

    def on_event(self, fn: Callable[[ThrowEvent], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, ev: ThrowEvent) -> None:
        self.history.append(ev)
        for fn in self._listeners:
            try:
                fn(ev)
            except Exception:                         # Listener dürfen die Engine nie reißen
                log.exception("Event-Listener fehlgeschlagen")

    # -- Hauptschleife ------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            frames = self.cameras.frames()
            if not any(frames):
                time.sleep(0.2)
                continue

            states: list[MotionState] = []
            bboxes: list[tuple[int, int, int, int] | None] = []
            for i, (det, fr) in enumerate(zip(self.detectors, frames)):
                if fr is None:
                    states.append(MotionState.IDLE)
                    bboxes.append(None)
                    continue
                if self._refs[i] is None:
                    self._refs[i] = fr.image.copy()
                res = det.process(fr.image)
                states.append(res.state)
                bboxes.append(res.bbox)

            if MotionState.TAKEOUT_PENDING in states and not self._takeout_announced:
                self._takeout_announced = True
                self._emit(ThrowEvent(kind="takeout_started"))

            if any(s == MotionState.TAKEOUT_DONE for s in states):
                self._finish_takeout(frames)
            elif any(s == MotionState.SETTLED for s in states):
                # Kurz warten, damit auch die anderen Kameras ruhig sind
                time.sleep(0.05)
                self._handle_throw(frames, bboxes)

            time.sleep(0.01)

    # -- Ereignisse ---------------------------------------------------------
    def _handle_throw(self, frames: list, bboxes: list) -> None:
        reads: list[CameraRead] = []
        debug: dict[str, Any] = {}
        for i, fr in enumerate(frames):
            if fr is None or self._refs[i] is None or bboxes[i] is None:
                continue
            cal = self.calib.cams.get(i)
            if cal is None:
                continue
            center_px = (cal.ellipse[0], cal.ellipse[1])
            tip = detect_tip(fr.image, self._refs[i], bboxes[i], center_px, self.cfg)
            if tip is None:
                continue
            x_mm, y_mm = cal.image_to_board(tip.tip_px)
            reads.append(CameraRead(i, x_mm, y_mm, tip.confidence))
            debug[f"cam{i}"] = {"tip_px": tip.tip_px, "mm": (round(x_mm, 1), round(y_mm, 1)),
                                "conf": round(tip.confidence, 2)}

        fused = fuse(reads, self.cfg) if reads else None
        if fused is None:
            self._emit(ThrowEvent(kind="status", detail={"msg": "Wurf verworfen", **debug}))
        else:
            sc = score_point(fused.x_mm, fused.y_mm, self.cfg)
            self.turn.append(sc)
            self._emit(ThrowEvent(kind="throw", score=sc, point=fused, detail=debug))

        # Neue Referenz: der steckende Dart gehört jetzt zur Szene
        self._acknowledge(frames)

    def _finish_takeout(self, frames: list) -> None:
        self.turn.clear()
        self._takeout_announced = False
        self._acknowledge(frames)
        self._emit(ThrowEvent(kind="takeout_finished"))

    def _acknowledge(self, frames: list) -> None:
        for i, fr in enumerate(frames):
            if fr is not None:
                self._refs[i] = fr.image.copy()
                self.detectors[i].acknowledge(fr.image)

    # -- Status für die API -------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return {
            "cameras": [
                {"no": i, "index": s.state.index, "connected": s.state.connected,
                 "calibrated": i in self.calib.cams,
                 "motion_state": self.detectors[i].state.value}
                for i, s in enumerate(self.cameras.sources)
            ],
            "turn": [s.label for s in self.turn],
        }
