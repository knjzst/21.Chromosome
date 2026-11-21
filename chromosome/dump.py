"""Debug-Dumps (Autodarts-Prinzip 9): bei Fehlwürfen Kontext als Archiv sichern.

Ein Dump enthält Config-Snapshot, aktuelle Frames aller Kameras und die letzten
Events – damit lässt sich ein Fehlwurf ohne Live-Zugriff nachstellen und die
Crops dienen später als Trainingsmaterial für ein eigenes Keypoint-Netz.
"""
from __future__ import annotations

import json
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

import cv2

from .config import Config
from .engine import Engine


def create_dump(engine: Engine, cfg: Config, comment: str = "") -> Path:
    out_dir = Path(cfg.get("dump.dir", "dumps"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"dump-{stamp}.zip"

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("config.json", json.dumps(cfg.snapshot(), indent=2, default=str))
        zf.writestr("comment.txt", comment)
        events = []
        for ev in engine.history:
            events.append({
                "kind": ev.kind, "ts": ev.ts,
                "score": asdict(ev.score) if ev.score else None,
                "point": asdict(ev.point) if ev.point else None,
                "detail": ev.detail,
            })
        zf.writestr("events.json", json.dumps(events, indent=2, default=str))
        for i, fr in enumerate(engine.cameras.frames()):
            if fr is None:
                continue
            ok, buf = cv2.imencode(".jpg", fr.image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok:
                zf.writestr(f"cam{i}.jpg", buf.tobytes())
    return path
