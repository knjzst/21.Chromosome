"""Einstieg: python -m chromosome [--config pfad/zur/config.toml]"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .api import build_app
from .config import DEFAULT_PATH, Config
from .engine import Engine


def main() -> None:
    parser = argparse.ArgumentParser(description="21.Chromosome Dart-Engine")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = Config(args.config)
    engine = Engine(cfg)
    engine.start()

    app = build_app(engine, cfg)
    try:
        # threaded=True: SSE- und MJPEG-Streams blockieren sonst alles.
        app.run(host=cfg.get("api.host", "0.0.0.0"),
                port=int(cfg.get("api.port", 3180)),
                threaded=True)
    finally:
        engine.stop()


if __name__ == "__main__":
    main()
