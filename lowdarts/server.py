"""Tiny web UI (stdlib only – no Flask, no Node, no browser on the device).

Open http://<device>:8080 on a phone, tablet or TV.  Server-Sent Events push
the game state; /setup lets you calibrate each camera by clicking 4 points.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2
import numpy as np

from . import board as B
from . import calibration
from .game import X01, parse_label

log = logging.getLogger("lowdarts")
STATIC = Path(__file__).with_name("static")


class App:
    def __init__(self, engine=None, sources=None, calib_path="calibration.json"):
        self.engine = engine
        self.sources = sources or []
        self.calib_path = calib_path
        self.game = X01(["Spieler 1", "Spieler 2"])
        self.last_hits: list[dict] = []
        self.status = ""
        self.lock = threading.RLock()
        self.subs: list[queue.Queue] = []

    # -- engine callback ---------------------------------------------------
    def on_event(self, ev):
        with self.lock:
            if ev.kind == "dart":
                self.game.throw(ev.hit)
                flag = "" if ev.confident else " – bitte prüfen!"
                self.status = f"{ev.hit.label} ({ev.info}, Kameras {ev.cams}){flag}"
            elif ev.kind == "takeout":
                if self.game.turn or self.game.bust:
                    self.game.next_player()
                self.status = "Darts gezogen"
            else:
                self.status = ev.info
        self.broadcast()

    def state(self) -> dict:
        with self.lock:
            s = self.game.state()
            s["status"] = self.status
            s["engine"] = self.engine.state if self.engine else "off"
            return s

    def broadcast(self):
        data = json.dumps(self.state())
        for q in list(self.subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    # -- actions -----------------------------------------------------------
    def action(self, name: str, body: dict) -> dict:
        with self.lock:
            g = self.game
            if name == "new_game":
                players = [p for p in body.get("players", []) if p.strip()] or ["Spieler 1"]
                self.game = X01(players, int(body.get("start", 501)),
                                bool(body.get("double_out", True)),
                                bool(body.get("double_in", False)))
                if self.engine:
                    self.engine.reset_reference()
            elif name == "next":
                g.next_player()
                if self.engine:
                    self.engine.reset_reference()
            elif name == "undo":
                g.undo()
            elif name == "throw":
                g.throw(parse_label(body["label"]))
            elif name == "correct":
                g.correct(int(body["index"]), parse_label(body["label"]))
            elif name == "rearm":
                if self.engine:
                    self.engine.reset_reference()
            else:
                raise KeyError(name)
        self.broadcast()
        return self.state()

    # -- calibration -------------------------------------------------------
    def snapshot(self, i: int, overlay: bool) -> bytes:
        _, fr = self.sources[i].latest()
        img = fr.full().copy()
        if overlay and self.engine and i < len(self.engine.geoms):
            draw_overlay(img, self.engine.geoms[i])
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    def calibrate(self, i: int, points) -> dict:
        _, fr = self.sources[i].latest()
        img = fr.full()
        g = calibration.from_clicks(points, (img.shape[1], img.shape[0]))
        g2, score = calibration.refine(img, g, levels=3)
        if score < 0.5:
            g2 = g  # refinement failed – keep the clicked version
        eng = self.engine
        while len(eng.geoms) <= i:
            eng.geoms.append(g2)
        eng.geoms[i] = g2
        from .detector import roi_mask
        eng.rois = [roi_mask(g) for g in eng.geoms]
        eng.small_rois = []
        calibration.save(self.calib_path, eng.geoms)
        eng.reset_reference()
        return {"ok": True, "ecc": round(score, 3)}


def draw_overlay(img, geom):
    for r in (B.R_BULL, B.R_OUTER_BULL, B.R_TRIPLE_IN, B.R_TRIPLE_OUT,
              B.R_DOUBLE_IN, B.R_DOUBLE_OUT):
        ang = np.linspace(0, 2 * np.pi, 90)
        pts = geom.board_to_image(np.c_[r * np.cos(ang), r * np.sin(ang)])
        cv2.polylines(img, [pts.astype(np.int32)], True, (0, 255, 255), 1, cv2.LINE_AA)
    for k in range(20):
        a = np.radians(90 - 9 - 18 * k)
        p = geom.board_to_image([[B.R_OUTER_BULL * np.cos(a), B.R_OUTER_BULL * np.sin(a)],
                                 [B.R_DOUBLE_OUT * np.cos(a), B.R_DOUBLE_OUT * np.sin(a)]])
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (0, 255, 255), 1)


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/setup":
                return self._send(200, (STATIC / "setup.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, json.dumps(app.state()).encode())
            if path == "/api/cameras":
                return self._send(200, json.dumps({
                    "count": len(app.sources),
                    "points": B.CALIBRATION_NAMES}).encode())
            if path.startswith("/cam/"):
                name = path.split("/")[-1]
                i = int(name.split(".")[0].split("_")[0])
                try:
                    return self._send(200, app.snapshot(i, "_overlay" in name), "image/jpeg")
                except (IndexError, AttributeError):
                    return self._send(404, b"{}")
            if path == "/events":
                q: queue.Queue = queue.Queue(maxsize=20)
                app.subs.append(q)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(f"data: {json.dumps(app.state())}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            data = q.get(timeout=15)
                            self.wfile.write(f"data: {data}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    app.subs.remove(q)
                return
            self._send(404, b"{}")

        def do_POST(self):
            path = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if path.startswith("/api/calibrate/"):
                    i = int(path.rsplit("/", 1)[1])
                    res = app.calibrate(i, body["points"])
                elif path.startswith("/api/"):
                    res = app.action(path[5:], body)
                else:
                    return self._send(404, b"{}")
                self._send(200, json.dumps(res).encode())
            except (KeyError, ValueError, IndexError, TypeError) as e:
                self._send(400, json.dumps({"error": str(e)}).encode())

    return H


def serve(app: App, host="0.0.0.0", port=8080):
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    srv.daemon_threads = True
    log.info("UI: http://%s:%d  (Kalibrierung: /setup)", host, port)
    srv.serve_forever()
