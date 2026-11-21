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

_INDEX_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>21.Chromosome</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, sans-serif; background:#111; color:#eee; margin:2rem; }
  h1 { font-size:1.4rem; } h2 { font-size:1.05rem; margin-top:1.6rem; }
  table { border-collapse:collapse; } td,th { padding:.35rem .8rem; border:1px solid #444; }
  .ok { color:#6c6; } .bad { color:#e66; }
  #turn { font-size:2.2rem; letter-spacing:.3rem; min-height:2.6rem; }
  #events { font-family:monospace; font-size:.85rem; white-space:pre-wrap;
            background:#1a1a1a; padding:.8rem; max-height:14rem; overflow-y:auto; }
  a { color:#8cf; }
</style></head><body>
<h1>21.Chromosome &ndash; Dart-Engine</h1>
<div id="turn">&ndash;</div>
<h2>Kameras</h2>
<table id="cams"><tr><th>Index</th><th>Verbunden</th><th>Kalibriert</th><th>Motion</th><th>Bild</th></tr></table>
<h2>Ereignisse</h2>
<div id="events"></div>
<p><a href="/api/state/stats">stats</a> &middot; <a href="/api/config/dynamic">config</a></p>
<script>
async function refresh() {
  const r = await fetch('/api/state/stats'); const s = await r.json();
  document.getElementById('turn').textContent = s.turn.length ? s.turn.join('  ') : '\\u2013';
  const t = document.getElementById('cams');
  while (t.rows.length > 1) t.deleteRow(1);
  for (const c of s.cameras) {
    const row = t.insertRow();
    row.insertCell().textContent = c.index;
    row.insertCell().innerHTML = c.connected ? '<span class="ok">ja</span>' : '<span class="bad">nein</span>';
    row.insertCell().innerHTML = c.calibrated ? '<span class="ok">ja</span>' : '<span class="bad">nein</span>';
    row.insertCell().textContent = c.motion_state;
    row.insertCell().innerHTML = '<a href="/api/streams/cams/' + c.no + '">Stream</a>';
  }
}
refresh(); setInterval(refresh, 2000);
const log = document.getElementById('events');
new EventSource('/api/events').onmessage = (e) => {
  const d = JSON.parse(e.data);
  const line = new Date(d.ts * 1000).toLocaleTimeString() + '  ' + d.kind +
               (d.score ? '  ' + d.score.label : '');
  log.textContent = line + '\\n' + log.textContent;
};
</script></body></html>
"""


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

    @app.get("/")
    def index():
        return Response(_INDEX_HTML, mimetype="text/html")

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
