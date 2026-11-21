"""Konfiguration: config.toml laden, zur Laufzeit patchbar (Autodarts-Prinzip 11)."""
from __future__ import annotations

import threading
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.toml"


class Config:
    """Threadsicherer Konfigurationsbaum mit Dot-Pfad-Zugriff.

    get("motion.diff_threshold") liefert den Wert; patch({"motion": {...}})
    ändert Werte zur Laufzeit (für PATCH /api/config/dynamic).
    """

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            with open(self._path, "rb") as fh:
                self._data = tomllib.load(fh)

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def section(self, name: str) -> dict[str, Any]:
        with self._lock:
            value = self._data.get(name, {})
            return dict(value) if isinstance(value, dict) else {}

    def patch(self, changes: dict[str, Any]) -> None:
        """Verschachteltes Dict in die Konfiguration mergen (nur zur Laufzeit, nicht persistent)."""
        def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
            for key, value in src.items():
                if isinstance(value, dict) and isinstance(dst.get(key), dict):
                    merge(dst[key], value)
                else:
                    dst[key] = value

        with self._lock:
            merge(self._data, changes)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            import copy
            return copy.deepcopy(self._data)
