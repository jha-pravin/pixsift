"""Desktop app: runs the engine on a private localhost port and shows the UI in a native window
(WKWebView on macOS, WebView2 on Windows)."""

import os
import socket
import sys
import threading
import time

import uvicorn
import webview

from .api import create_app
from .config import Settings


class Bridge:
    """Functions the UI can call through window.pywebview.api."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None  # private: pywebview exposes public attributes to JS

    def pick_folders(self) -> list[str]:
        """Native folder chooser; Cmd/Ctrl- or Shift-click selects several folders at once."""
        if not self._window:
            return []
        return list(self._window.create_file_dialog(webview.FileDialog.FOLDER, allow_multiple=True) or [])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_engine(settings: Settings) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=settings.port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="pixsift-server")
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        if time.time() > deadline or not thread.is_alive():
            sys.exit("PixSift engine failed to start")
        time.sleep(0.05)
    return server, thread


def self_test() -> int:
    """`PixSift --self-test`: start the engine on a throwaway library and check it answers, without a window.
    Used by CI to prove a packaged build has all its native libraries and the UI bundled."""
    import json
    import tempfile
    import urllib.error
    import urllib.request
    from pathlib import Path

    from . import analyzer  # noqa: F401  (imports OpenCV, ONNX Runtime, tokenizers)
    from . import faces  # noqa: F401  (imports scikit-learn)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(data_dir=Path(tmp), port=_free_port())
        server, thread = _start_engine(settings)
        base = f"http://127.0.0.1:{settings.port}"
        try:
            try:
                urllib.request.urlopen(f"{base}/api/health")
                return 1  # must be refused without the token
            except urllib.error.HTTPError as e:
                if e.code != 401:
                    return 1
            req = urllib.request.Request(f"{base}/api/health", headers={"Cookie": f"pixsift_token={settings.token}"})
            health = json.load(urllib.request.urlopen(req))
            ui = urllib.request.urlopen(f"{base}/").read().decode()
            from . import decode
            fast_decoder = sys.platform != "darwin" or decode.Quartz is not None  # ImageIO bundled on macOS
            ok = health.get("version") and '<div id="root">' in ui and fast_decoder
            if sys.stdout:  # windowed builds have no console
                print(f"PixSift {health.get('version')} self-test {'passed' if ok else 'FAILED'}")
            return 0 if ok else 1
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    settings = Settings(port=_free_port())
    server, thread = _start_engine(settings)
    bridge = Bridge()
    bridge._window = webview.create_window(
        "PixSift", settings.url, js_api=bridge, width=1320, height=860, min_size=(900, 600),
    )
    webview.start(private_mode=False)  # keep localStorage (viewer preferences) between launches
    server.should_exit = True
    thread.join(timeout=5)
    # Exit even if an analysis thread is stuck on a bad file or a sleeping drive (Python would wait for it).
    # Everything is already committed to SQLite.
    os._exit(0)


if __name__ == "__main__":
    main()
