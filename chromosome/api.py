"""Lokale REST-API (Flask) – Engine und UI sind entkoppelt (Autodarts-Prinzip 8).

Routenschema bewusst an die lokale Autodarts-Board-API angelehnt:
  GET  /api/state/stats                  Status (Kameras, Motion-Zustand, aktueller Turn)
  GET  /api/events                       Server-Sent Events (throw/takeout/status)
  GET  /api/img/cams/<n>                 Einzelbild Kamera n (JPEG)
  GET  /api/streams/cams/<n>             MJPEG-Stream Kamera n (gedrosselt)
  GET  /api/config/dynamic               aktuelle Konfiguration
  PATCH /api/config/dynamic              Schwellen zur Laufzeit ändern (JSON, nicht persistent)
  POST /api/config/reset                 config.toml neu laden
  POST /api/config/calibration/auto/<n>  Kamera n kalibrieren, Body: {"p20": [x, y]}
                                         (Bildpunkt der Mitte des 20er-Segments)
  POST /api/debug/dump                   Debug-Archiv erzeugen, Body: {"comment": "..."}
"""
from __future__ import annotations

import json
import math
import queue
import time

import cv2
from flask import Flask, Response, jsonify, request

from .config import Config
from .dump import create_dump
from .engine import Engine, ThrowEvent


def build_app(engine: Engine, cfg: Config) -> Flask:
    app = Flask("chromosome21")
    subscribers: list[queue.Queue] = []

    def fanout(ev: ThrowEvent) -> None:
        payload = {
            "kind": ev.kind, "ts": ev.ts,
            "score": ev.score.__dict__ if ev.score else None,
            "point": ev.point.__dict__ if ev.point else None,
            "detail": ev.detail,
        }
        for q in list(subscribers):
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    engine.on_event(fanout)

    @app.get("/api/state/stats")
    def stats():
        return jsonify(engine.stats())

    @app.get("/api/events")
    def events():
        q: queue.Queue = queue.Queue(maxsize=100)
        subscribers.append(q)

        def gen():
            try:
                while True:
                    try:
                        item = q.get(timeout=15)
                        yield f"data: {json.dumps(item, default=str)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                subscribers.remove(q)

        return Response(gen(), mimetype="text/event-stream")

    @app.get("/api/img/cams/<int:n>")
    def snapshot(n: int):
        fr = engine.cameras.sources[n].latest() if n < len(engine.cameras.sources) else None
        if fr is None:
            return jsonify({"error": "Kamera nicht verfügbar"}), 503
        ok, buf = cv2.imencode(".jpg", fr.image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.get("/api/streams/cams/<int:n>")
    def stream(n: int):
        if n >= len(engine.cameras.sources):
            return jsonify({"error": "Kamera nicht verfügbar"}), 404
        period = 1.0 / float(cfg.get("api.stream_fps", 10))

        def gen():
            while True:
                fr = engine.cameras.sources[n].latest()
                if fr is not None:
                    ok, buf = cv2.imencode(".jpg", fr.image, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                               + buf.tobytes() + b"\r\n")
                time.sleep(period)

        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/config/dynamic")
    def get_config():
        return jsonify(cfg.snapshot())

    @app.patch("/api/config/dynamic")
    def patch_config():
        changes = request.get_json(force=True, silent=True)
        if not isinstance(changes, dict):
            return jsonify({"error": "JSON-Objekt erwartet"}), 400
        cfg.patch(changes)
        return jsonify({"ok": True})

    @app.post("/api/config/reset")
    def reset_config():
        cfg.reload()
        return jsonify({"ok": True})

    @app.post("/api/config/calibration/auto/<int:n>")
    def calibrate(n: int):
        body = request.get_json(force=True, silent=True) or {}
        p20 = body.get("p20")
        if not (isinstance(p20, list) and len(p20) == 2):
            return jsonify({"error": "Body {\"p20\": [x, y]} erwartet "
                                     "(Bildpunkt Mitte 20er-Segment)"}), 400
        fr = engine.cameras.sources[n].latest() if n < len(engine.cameras.sources) else None
        if fr is None:
            return jsonify({"error": "Kamera nicht verfügbar"}), 503
        from .calibration import find_board_ellipse
        ell = find_board_ellipse(fr.image)
        if ell is None:
            return jsonify({"error": "Keine Board-Ellipse gefunden – Ausleuchtung/Sichtfeld prüfen"}), 422
        theta20 = math.atan2(float(p20[1]) - ell[1], float(p20[0]) - ell[0])
        calib = engine.calib.calibrate_camera(n, fr.image, theta20, ell)
        if calib is None:
            return jsonify({"error": "Homographie fehlgeschlagen"}), 422
        return jsonify({"ok": True, "ellipse": calib.ellipse})

    @app.post("/api/debug/dump")
    def dump():
        body = request.get_json(force=True, silent=True) or {}
        path = create_dump(engine, cfg, str(body.get("comment", "")))
        return jsonify({"ok": True, "path": str(path)})

    return app
