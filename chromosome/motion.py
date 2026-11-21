"""Bewegungsdetektor mit Zustandsautomat – das Herzstück der Low-HW-Strategie.

Autodarts-Prinzip 1: Die teure Analyse (Crop-Detection, später NN) läuft NUR,
wenn der billige Differenzbild-Detektor ein Ereignis meldet. Im Leerlauf kostet
die Engine pro Kamera nur ein Resize + absdiff auf 320x180 Graustufen.

Zustände (angelehnt an Autodarts ThrowDetected/TakeoutStarted/-Finished):

    IDLE ──Bewegung klein──▶ MOTION ──ruhig (min_dart_frames)──▶ SETTLED → Wurf-Analyse → IDLE
      │                        │
      └──Bewegung groß (Hand)──┴──▶ TAKEOUT_PENDING ──Hand weg + ruhig──▶ TAKEOUT_DONE → Referenz neu → IDLE
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

import cv2
import numpy as np

from .config import Config


class MotionState(enum.Enum):
    IDLE = "idle"
    MOTION = "motion"
    SETTLED = "settled"            # Dart gelandet -> Analyse auslösen
    TAKEOUT_PENDING = "takeout_in_progress"
    TAKEOUT_DONE = "takeout_finished"


@dataclass
class MotionResult:
    state: MotionState
    changed_pixels: int
    bbox: tuple[int, int, int, int] | None   # Änderungs-Bounding-Box im Vollbild
    diff_small: np.ndarray | None            # Debug: Differenzbild (verkleinert)


class MotionDetector:
    """Ein Detektor je Kamera. Referenzbild = Szene nach dem letzten Ereignis."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._ref: np.ndarray | None = None       # Referenz (verkleinert, Graustufen, geblurrt)
        self._state = MotionState.IDLE
        self._still_frames = 0
        self._hand_frames = 0
        self._frames_in_state = 0
        self._pending_bbox: tuple[int, int, int, int] | None = None

    @property
    def state(self) -> MotionState:
        return self._state

    def reset_reference(self, frame: np.ndarray) -> None:
        self._ref = self._prepare(frame)
        self._state = MotionState.IDLE
        self._still_frames = 0
        self._hand_frames = 0
        self._frames_in_state = 0
        self._pending_bbox = None

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        scale = float(self._cfg.get("processing.motion_scale", 0.25))
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def process(self, frame: np.ndarray) -> MotionResult:
        m = self._cfg.section("motion")
        scale = float(self._cfg.get("processing.motion_scale", 0.25))

        cur = self._prepare(frame)
        if self._ref is None:
            self.reset_reference(frame)
            return MotionResult(self._state, 0, None, None)

        diff = cv2.absdiff(cur, self._ref)
        _, mask = cv2.threshold(diff, int(m["diff_threshold"]), 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, None, iterations=1)
        changed = int(cv2.countNonZero(mask))

        bbox = None
        if changed >= int(m["min_contour_area"]):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contours = [c for c in contours if cv2.contourArea(c) >= int(m["min_contour_area"])]
            if contours:
                xs, ys, ws, hs = zip(*(cv2.boundingRect(c) for c in contours))
                x0, y0 = min(xs), min(ys)
                x1 = max(x + w for x, w in zip(xs, ws))
                y1 = max(y + h for y, h in zip(ys, hs))
                inv = 1.0 / scale
                bbox = (int(x0 * inv), int(y0 * inv), int((x1 - x0) * inv), int((y1 - y0) * inv))

        self._frames_in_state += 1
        moving = changed >= int(m["min_change_pixels"])
        hand = changed >= int(m["hand_pixels"])

        if self._state == MotionState.IDLE:
            if hand:
                self._hand_frames += 1
                if self._hand_frames >= int(m["takeout_min_hand_frames"]):
                    self._to(MotionState.TAKEOUT_PENDING)
            elif moving:
                self._hand_frames = 0
                self._to(MotionState.MOTION)
                self._pending_bbox = bbox
            else:
                self._hand_frames = 0

        elif self._state == MotionState.MOTION:
            if hand:
                self._to(MotionState.TAKEOUT_PENDING)
            elif moving:
                self._still_frames = 0
                self._pending_bbox = bbox or self._pending_bbox
            else:
                self._still_frames += 1
                if self._still_frames >= int(m["min_dart_frames"]):
                    if 0 < changed <= int(m["max_dart_pixels"]):
                        self._to(MotionState.SETTLED)
                        bbox = self._pending_bbox
                    else:
                        # Zu große ruhige Änderung: Szene hat sich verschoben -> neu referenzieren
                        self.reset_reference(frame)
            if self._frames_in_state > int(m["settle_timeout_frames"]):
                self.reset_reference(frame)

        elif self._state == MotionState.TAKEOUT_PENDING:
            if not moving:
                self._still_frames += 1
                if self._still_frames >= int(m["takeout_wait_frames"]):
                    self._to(MotionState.TAKEOUT_DONE)
            else:
                self._still_frames = 0

        return MotionResult(self._state, changed, bbox if self._state == MotionState.SETTLED else bbox, diff)

    def acknowledge(self, frame: np.ndarray) -> None:
        """Nach ausgewertetem Wurf bzw. beendetem Takeout: neues Referenzbild setzen."""
        self.reset_reference(frame)

    def _to(self, state: MotionState) -> None:
        self._state = state
        self._still_frames = 0
        self._frames_in_state = 0
        if state != MotionState.IDLE:
            self._hand_frames = 0
