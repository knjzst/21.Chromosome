"""Kameraerfassung: ein Capture-Thread je USB-Kamera, MJPEG direkt vom UVC-Treiber.

Autodarts-Prinzip 7: MJPEG vom Treiber dekodieren statt RAW über USB zu ziehen –
drei 720p-Kameras an einem Pi 4 gehen sonst an der USB-Bandbreite kaputt.
Jeder Thread hält nur den jeweils letzten Frame vor (kein Queue-Stau).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import Config


@dataclass
class Frame:
    image: np.ndarray
    ts: float
    seq: int


@dataclass
class CameraState:
    index: int
    connected: bool = False
    last_frame: Frame | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class CameraSource:
    """Hintergrund-Thread für eine Kamera; stellt immer den neuesten Frame bereit."""

    def __init__(self, device_index: int, cfg: Config) -> None:
        self._cfg = cfg
        self.state = CameraState(index=device_index)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"cam{device_index}")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def latest(self) -> Frame | None:
        with self.state.lock:
            return self.state.last_frame

    def _open(self) -> cv2.VideoCapture:
        cam = self._cfg.section("cameras")
        cap = cv2.VideoCapture(self.state.index, cv2.CAP_V4L2)
        fourcc = cv2.VideoWriter_fourcc(*cam.get("fourcc", "MJPG"))
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam.get("width", 1280))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam.get("height", 720))
        cap.set(cv2.CAP_PROP_FPS, cam.get("fps", 30))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keinen alten Frame nachziehen
        return cap

    def _run(self) -> None:
        seq = 0
        cap: cv2.VideoCapture | None = None
        while not self._stop.is_set():
            if cap is None or not cap.isOpened():
                cap = self._open()
                self.state.connected = cap.isOpened()
                if not self.state.connected:
                    time.sleep(2.0)  # Kamera weg? Später erneut versuchen (Hotplug)
                    continue
            ok, img = cap.read()
            if not ok:
                cap.release()
                cap = None
                self.state.connected = False
                continue
            seq += 1
            with self.state.lock:
                self.state.last_frame = Frame(image=img, ts=time.monotonic(), seq=seq)
        if cap is not None:
            cap.release()


class CameraSet:
    """Alle konfigurierten Kameras; liefert zeitlich zusammengehörige Frame-Gruppen."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        indices = cfg.get("cameras.indices", [0])
        self.sources = [CameraSource(i, cfg) for i in indices]

    def start(self) -> None:
        for src in self.sources:
            src.start()

    def stop(self) -> None:
        for src in self.sources:
            src.stop()

    def frames(self) -> list[Frame | None]:
        return [src.latest() for src in self.sources]

    def connected(self) -> list[bool]:
        return [src.state.connected for src in self.sources]
