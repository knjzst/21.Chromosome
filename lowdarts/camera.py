"""Low-overhead camera capture.

Tricks that cut CPU and USB load compared to "decode every frame at 30 FPS":

* MJPEG from the camera: ~10x less USB bandwidth than YUYV, so three cameras
  fit on ONE USB 2.0 controller.
* Low frame rate while idle (default 10 FPS).  We never need to see the
  dart in flight – only "before" and "after" stable frames.
* Motion check on a JPEG decoded at 1/4 or 1/8 scale (libjpeg DCT scaling
  via IMREAD_REDUCED_GRAYSCALE_*), which is several times cheaper than a full
  decode.  Full-resolution decode only happens for the few frames that are
  actually analysed.
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np

_REDUCED = {1: cv2.IMREAD_GRAYSCALE, 2: cv2.IMREAD_REDUCED_GRAYSCALE_2,
            4: cv2.IMREAD_REDUCED_GRAYSCALE_4, 8: cv2.IMREAD_REDUCED_GRAYSCALE_8}


class Frame:
    """A captured frame that is decoded lazily."""

    __slots__ = ("_jpeg", "_full", "_small", "ts", "scale")

    def __init__(self, jpeg: bytes | None = None, full: np.ndarray | None = None,
                 ts: float = 0.0, scale: int = 4):
        self._jpeg, self._full, self._small = jpeg, full, None
        self.ts, self.scale = ts, scale

    def small(self) -> np.ndarray:
        """Small grayscale image for motion detection."""
        if self._small is None:
            if self._jpeg is not None:
                self._small = cv2.imdecode(np.frombuffer(self._jpeg, np.uint8),
                                           _REDUCED[self.scale])
            else:
                f = self.full()
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
                self._small = cv2.resize(g, (g.shape[1] // self.scale,
                                             g.shape[0] // self.scale),
                                         interpolation=cv2.INTER_AREA)
        return self._small

    def full(self) -> np.ndarray:
        if self._full is None:
            self._full = cv2.imdecode(np.frombuffer(self._jpeg, np.uint8),
                                      cv2.IMREAD_COLOR)
        return self._full


class Camera:
    """Threaded V4L2/DirectShow camera that always holds the latest frame."""

    def __init__(self, source, size=(640, 480), fps=10, scale=4):
        self.source, self.size, self.fps, self.scale = source, size, fps, scale
        self.cap = None
        self.raw = False
        self._latest: Frame | None = None
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def open(self):
        src = int(self.source) if str(self.source).isdigit() else self.source
        cap = cv2.VideoCapture(src, cv2.CAP_V4L2) if isinstance(src, int) else None
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise RuntimeError(f"camera {self.source} not available")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # try to get the raw JPEG buffer (no decode in the driver thread)
        try:
            self.raw = bool(cap.set(cv2.CAP_PROP_CONVERT_RGB, 0))
        except cv2.error:
            self.raw = False
        self.cap = cap
        ok, test = cap.read()
        if ok and self.raw and not (test.ndim <= 2 and test.size > 2
                                    and test.ravel()[0] == 0xFF):
            # backend ignored CONVERT_RGB=0 -> decoded frames
            self.raw = False
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)
        self.size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.size[0],
                     int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.size[1])
        return self

    def start(self):
        if self.cap is None:
            self.open()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        period = 1.0 / max(self.fps, 1)
        while not self._stop.is_set():
            t0 = time.monotonic()
            ok, img = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            if self.raw:
                fr = Frame(jpeg=img.tobytes(), ts=t0, scale=self.scale)
            else:
                fr = Frame(full=img, ts=t0, scale=self.scale)
            with self._lock:
                self._latest = fr
                self._seq += 1
            # drivers that ignore CAP_PROP_FPS: throttle ourselves
            dt = time.monotonic() - t0
            if dt < period * 0.5:
                time.sleep(period - dt)

    def latest(self) -> tuple[int, Frame | None]:
        with self._lock:
            return self._seq, self._latest

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self.cap:
            self.cap.release()


class SimSource:
    """Drop-in replacement for Camera backed by a sim.SimCamera."""

    def __init__(self, sim_cam, scale=4, jpeg_quality=90):
        self.sim, self.scale, self.q = sim_cam, scale, jpeg_quality
        self.size = (sim_cam.w, sim_cam.h)
        self._seq = 0
        self._dirty = True
        self._frame = None

    def start(self):
        return self

    def invalidate(self):
        self._dirty = True

    def latest(self):
        if self._dirty:
            img = self.sim.render()
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.q])
            self._frame = Frame(jpeg=buf.tobytes(), ts=time.monotonic(),
                                scale=self.scale)
            self._dirty = False
        self._seq += 1
        return self._seq, self._frame

    def stop(self):
        pass
