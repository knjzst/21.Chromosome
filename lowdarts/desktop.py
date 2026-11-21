"""Desktop window.

Uses pywebview (Edge WebView2 on Windows – already part of Windows 10/11).
Falls back to the default browser if pywebview is not installed.
"""
from __future__ import annotations

import logging
import threading
import webbrowser

from .server import make_server

log = logging.getLogger("lowdarts")


def run_desktop(app, fullscreen: bool = False, port: int = 0):
    srv = make_server(app, "127.0.0.1", port)   # port 0 = any free port
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import webview  # type: ignore
    except ImportError:
        log.warning("pywebview fehlt – öffne im Browser: %s", url)
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return
    webview.create_window("LowDarts", url, width=1360, height=860, min_size=(900, 620),
                          fullscreen=fullscreen, background_color="#0c111d")
    try:
        webview.start()
    finally:
        app.stop_cameras()
        srv.shutdown()
