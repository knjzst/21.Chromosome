"""Local app server: game control, bots, settings, sounds, cameras.

Stdlib HTTP only.  The desktop window (pywebview) or any browser on the LAN
talks to it; Server-Sent Events push the state.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2
import numpy as np

from . import board as B
from . import calibration
from .bot import Bot
from .game import parse_label
from .modes import create

log = logging.getLogger("lowdarts")
STATIC = Path(__file__).with_name("static")

DEFAULT_SETTINGS = {
    "caller": {"enabled": True, "lang": "de-DE", "voice": "", "rate": 1.0,
               "pitch": 1.0, "volume": 1.0, "call_checkout": True},
    "sounds": {"enabled": True, "volume": 0.8, "events": {}},   # event -> custom file
    "pads": [],            # custom soundboard pads: {"name", "file"}
    "players": ["Spieler 1", "Spieler 2"],
    "walkon": {},          # player name -> sound file
    "cameras": [],         # list of sources ("0", "1", "http://...")
    "cam_res": "640x480",
    "cam_fps": 10,
    "animations": True,
    "theme": "night",
}

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        d = base / "LowDarts"
    else:
        d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "lowdarts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sounds").mkdir(exist_ok=True)
    return d


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class App:
    def __init__(self, data: Path | None = None, engine=None, sources=None):
        self.data = Path(data) if data else data_dir()
        (self.data / "sounds").mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.subs: list[queue.Queue] = []
        self.settings = self._load_settings()
        self.engine = engine
        self.sources = sources or []
        self.status = ""
        self.config = {"mode": "x01", "options": {"start": 501},
                       "players": [{"name": n, "bot": 0} for n in self.settings["players"]]}
        self.bots: dict[int, Bot] = {}
        self.game = create("x01", self.settings["players"], start=501)
        self.match_saved = False
        self.seq = 0          # bumps on every game change -> UI plays events once
        self._bot_stop = threading.Event()
        threading.Thread(target=self._bot_loop, daemon=True).start()

    # -- persistence -----------------------------------------------------------
    def _load_settings(self) -> dict:
        p = self.data / "settings.json"
        try:
            return _merge(DEFAULT_SETTINGS, json.loads(p.read_text("utf-8")))
        except (OSError, ValueError):
            return json.loads(json.dumps(DEFAULT_SETTINGS))

    def save_settings(self):
        (self.data / "settings.json").write_text(
            json.dumps(self.settings, indent=2, ensure_ascii=False), "utf-8")

    def _save_match(self):
        s = self.game.state()
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M"), "mode": s["mode"], "title": s["title"],
               "winner": s["players"][s["winner"]]["name"] if s["winner"] is not None else None,
               "players": [{k: v for k, v in p.items() if k not in ("marks", "checkout")}
                           for p in s["players"]],
               "bots": {str(k): b.level for k, b in self.bots.items()}}
        with open(self.data / "matches.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def matches(self, limit=200) -> list[dict]:
        p = self.data / "matches.jsonl"
        if not p.exists():
            return []
        rows = [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]
        return rows[-limit:][::-1]

    # -- state -----------------------------------------------------------------
    def state(self) -> dict:
        with self.lock:
            s = self.game.state()
            s["status"] = self.status
            s["engine"] = self.engine.state if self.engine else "off"
            s["cameras"] = len(self.sources)
            s["bots"] = {str(k): b.level for k, b in self.bots.items()}
            s["config"] = self.config
            s["seq"] = self.seq
            return s

    def broadcast(self):
        data = json.dumps(self.state(), ensure_ascii=False)
        for q in list(self.subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def _after_action(self):
        self.seq += 1
        if self.game.finished and not self.match_saved:
            self.match_saved = True
            try:
                self._save_match()
            except OSError:
                log.exception("could not save match")
        self.broadcast()

    # -- engine callback -------------------------------------------------------
    def on_event(self, ev):
        with self.lock:
            if self.game.current in self.bots:
                return  # bot's turn – ignore the board
            if ev.kind == "dart":
                self.game.throw(ev.hit)
                flag = "" if ev.confident else " – bitte prüfen!"
                self.status = f"{ev.hit.label} erkannt{flag}"
            elif ev.kind == "takeout":
                if self.game.turn or self.game.turn_done:
                    self.game.next_turn()
                self.status = "Darts gezogen"
            else:
                self.status = {"occluded": "Hand im Bild", "no dart found": "Kein Dart gefunden"}.get(ev.info, ev.info)
        self._after_action()

    # -- bots ------------------------------------------------------------------
    def _bot_loop(self):
        last = 0.0
        while not self._bot_stop.is_set():
            time.sleep(0.1)
            with self.lock:
                g = self.game
                if g.finished or g.current not in self.bots:
                    last = time.monotonic()
                    continue
                now = time.monotonic()
                wait = 1.6 if g.turn_done else 0.9
                if now - last < wait:
                    continue
                last = now
                if g.turn_done:
                    g.next_turn()
                else:
                    g.throw(self.bots[g.current].next_dart(g.state()))
            self._after_action()

    # -- actions ---------------------------------------------------------------
    def action(self, name: str, body: dict) -> dict:
        with self.lock:
            g = self.game
            if name == "new_game":
                players = body.get("players") or [{"name": "Spieler 1", "bot": 0}]
                players = [p for p in players if str(p.get("name", "")).strip()][:8] or \
                    [{"name": "Spieler 1", "bot": 0}]
                mode = body.get("mode", "x01")
                opts = body.get("options", {})
                self.game = create(mode, [p["name"] for p in players], **opts)
                self.bots = {i: Bot(int(p["bot"])) for i, p in enumerate(players) if int(p.get("bot") or 0)}
                self.config = {"mode": mode, "options": opts, "players": players}
                self.match_saved = False
                humans = [p["name"] for p in players if not int(p.get("bot") or 0)]
                if humans:
                    self.settings["players"] = humans
                    self.save_settings()
                if self.engine:
                    self.engine.reset_reference()
                self.status = ""
                self.game.events = ["game_start"]
            elif name == "rematch":
                return self.action("new_game", self.config)
            elif name == "next":
                g.next_turn()
                if self.engine:
                    self.engine.reset_reference()
            elif name == "undo":
                g.undo()
            elif name == "throw":
                if "label" in body:
                    hit = parse_label(body["label"])
                else:
                    hit = B.score_point(float(body["x"]), float(body["y"]))
                g.throw(hit)
            elif name == "correct":
                g.correct(int(body["index"]), parse_label(body["label"]))
            elif name == "rearm":
                if self.engine:
                    self.engine.reset_reference()
            else:
                raise KeyError(name)
        self._after_action()
        return self.state()

    # -- settings & sounds -------------------------------------------------------
    def update_settings(self, body: dict) -> dict:
        with self.lock:
            self.settings = _merge(self.settings, body)
            self.save_settings()
        return self.settings

    def upload_sound(self, filename: str, data: bytes) -> str:
        if not data:
            raise ValueError("Leere Datei")
        if len(data) > 15 * 1024 * 1024:
            raise ValueError("Datei zu groß (max. 15 MB)")
        stem, ext = os.path.splitext(os.path.basename(filename))
        if ext.lower() not in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"):
            raise ValueError("Nur Audio-Dateien (mp3, wav, ogg, m4a, aac, flac)")
        name = SAFE_NAME.sub("_", stem)[:60] + ext.lower()
        target = self.data / "sounds" / name
        k = 1
        while target.exists():
            target = self.data / "sounds" / f"{SAFE_NAME.sub('_', stem)[:55]}_{k}{ext.lower()}"
            k += 1
        target.write_bytes(data)
        return target.name

    def list_sounds(self) -> list[str]:
        return sorted(p.name for p in (self.data / "sounds").iterdir() if p.is_file())

    # -- cameras ----------------------------------------------------------------
    def snapshot(self, i: int, overlay: bool) -> bytes:
        _, fr = self.sources[i].latest()
        img = fr.full().copy()
        if overlay and self.engine and i < len(self.engine.geoms):
            draw_overlay(img, self.engine.geoms[i])
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    def calibrate(self, i: int, points) -> dict:
        from .detector import roi_mask
        _, fr = self.sources[i].latest()
        img = fr.full()
        g = calibration.from_clicks(points, (img.shape[1], img.shape[0]))
        g2, score = calibration.refine(img, g, levels=3)
        if score < 0.5:
            g2 = g
        eng = self.engine
        eng.geoms[i] = g2
        eng.rois = [roi_mask(x) for x in eng.geoms]
        eng.small_rois = []
        calibration.save(self.data / "calibration.json", eng.geoms,
                         {"sources": [str(s) for s in self.settings["cameras"]],
                          "calibrated": self._calibrated_flags(i)})
        eng.reset_reference()
        return {"ok": True, "ecc": round(score, 3)}

    def _calibrated_flags(self, newly: int) -> list[bool]:
        flags = getattr(self, "_cal_flags", [False] * len(self.sources))
        flags = (flags + [False] * len(self.sources))[:len(self.sources)]
        flags[newly] = True
        self._cal_flags = flags
        return flags

    def start_cameras(self, sources: list[str]) -> dict:
        from .camera import Camera
        from .engine import Engine, EngineConfig
        from .sim import default_rig
        self.stop_cameras()
        w, h = map(int, self.settings["cam_res"].split("x"))
        fps = float(self.settings["cam_fps"])
        cams = []
        for s in sources:
            try:
                cams.append(Camera(s, (w, h), fps).start())
            except RuntimeError as e:
                for c in cams:
                    c.stop()
                raise ValueError(str(e))
        geoms, flags = None, [False] * len(cams)
        cal = self.data / "calibration.json"
        if cal.exists():
            try:
                g, meta = calibration.load(cal)
                if meta.get("sources") == [str(s) for s in sources]:
                    geoms, flags = g, meta.get("calibrated", [True] * len(g))
            except (OSError, ValueError, KeyError):
                pass
        if geoms is None:
            rig = default_rig(size=(w, h))
            geoms = [rig[i % 3].true_geometry() for i in range(len(cams))]
        self._cal_flags = flags
        self.sources = cams
        self.settings["cameras"] = [str(s) for s in sources]
        self.save_settings()
        self.engine = Engine(cams, geoms, self.on_event, EngineConfig(fps=fps))
        self.engine.start()
        self.broadcast()
        return {"ok": True, "calibrated": flags}

    def stop_cameras(self):
        if self.engine:
            self.engine.stop()
        for s in self.sources:
            s.stop()
        self.engine, self.sources = None, []


def list_cameras(max_index=6) -> list[dict]:
    found = []
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    for i in range(max_index):
        cap = cv2.VideoCapture(i, backend)
        ok = cap.isOpened() and cap.read()[0]
        if ok:
            found.append({"source": str(i),
                          "label": f"Kamera {i + 1} ({int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
                                   f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})"})
        cap.release()
    return found


def draw_overlay(img, geom):
    for r in (B.R_BULL, B.R_OUTER_BULL, B.R_TRIPLE_IN, B.R_TRIPLE_OUT,
              B.R_DOUBLE_IN, B.R_DOUBLE_OUT):
        ang = np.linspace(0, 2 * np.pi, 90)
        pts = geom.board_to_image(np.c_[r * np.cos(ang), r * np.sin(ang)])
        cv2.polylines(img, [pts.astype(np.int32)], True, (0, 220, 255), 1, cv2.LINE_AA)
    for k in range(20):
        a = np.radians(90 - 9 - 18 * k)
        p = geom.board_to_image([[B.R_OUTER_BULL * np.cos(a), B.R_OUTER_BULL * np.sin(a)],
                                 [B.R_DOUBLE_OUT * np.cos(a), B.R_DOUBLE_OUT * np.sin(a)]])
        cv2.line(img, tuple(p[0].astype(int)), tuple(p[1].astype(int)), (0, 220, 255), 1)


# --------------------------------------------------------------------------
def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", cache=False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _file(self, path: Path):
            if not path.is_file():
                return self._send(404, b"{}")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                return self._file(STATIC / "index.html")
            if path.startswith("/static/"):
                p = (STATIC / path[8:]).resolve()
                if STATIC.resolve() in p.parents:
                    return self._file(p)
                return self._send(404, b"{}")
            if path.startswith("/sounds/"):
                p = (app.data / "sounds" / os.path.basename(path)).resolve()
                return self._file(p)
            if path == "/api/state":
                return self._json(app.state())
            if path == "/api/settings":
                return self._json(app.settings)
            if path == "/api/sounds":
                return self._json(app.list_sounds())
            if path == "/api/matches":
                return self._json(app.matches())
            if path == "/api/cameras":
                return self._json({"active": [str(s) for s in app.settings["cameras"]] if app.sources else [],
                                   "count": len(app.sources),
                                   "calibrated": getattr(app, "_cal_flags", []),
                                   "points": B.CALIBRATION_NAMES})
            if path == "/api/cameras/scan":
                return self._json(list_cameras())
            if path.startswith("/cam/"):
                name = path.split("/")[-1]
                try:
                    i = int(name.split(".")[0].split("_")[0])
                    return self._send(200, app.snapshot(i, "_overlay" in name), "image/jpeg")
                except (IndexError, AttributeError, ValueError):
                    return self._send(404, b"{}")
            if path == "/events":
                return self._events()
            self._send(404, b"{}")

        def _events(self):
            q: queue.Queue = queue.Queue(maxsize=50)
            app.subs.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(f"data: {json.dumps(app.state(), ensure_ascii=False)}\n\n".encode())
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

        def do_POST(self):
            path = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                if path == "/api/upload":
                    fname = unquote(self.headers.get("X-Filename", "sound.mp3"))
                    return self._json({"file": app.upload_sound(fname, raw)})
                body = json.loads(raw or b"{}")
                if path == "/api/settings":
                    return self._json(app.update_settings(body))
                if path.startswith("/api/calibrate/"):
                    return self._json(app.calibrate(int(path.rsplit("/", 1)[1]), body["points"]))
                if path == "/api/cameras/start":
                    return self._json(app.start_cameras([str(s) for s in body["sources"]]))
                if path == "/api/cameras/stop":
                    app.stop_cameras()
                    app.broadcast()
                    return self._json({"ok": True})
                if path.startswith("/api/"):
                    return self._json(app.action(path[5:], body))
                self._send(404, b"{}")
            except (KeyError, ValueError, IndexError, TypeError) as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001 – never leave the UI hanging
                log.exception("request %s failed", path)
                self._json({"error": f"Interner Fehler: {e}"}, 500)

    return H


def make_server(app: App, host="127.0.0.1", port=8080) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    srv.daemon_threads = True
    return srv


def serve(app: App, host="127.0.0.1", port=8080):
    srv = make_server(app, host, port)
    log.info("LowDarts: http://%s:%d", host, srv.server_address[1])
    srv.serve_forever()
