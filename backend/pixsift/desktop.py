"""Desktop app: runs the engine on a private localhost port and shows the UI in a native window
(WKWebView on macOS, WebView2 on Windows)."""

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


def main() -> None:
    settings = Settings(port=_free_port())
    port = settings.port
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="pixsift-server")
    thread.start()
    deadline = time.time() + 30
    while not server.started:
        if time.time() > deadline or not thread.is_alive():
            sys.exit("PixSift engine failed to start")
        time.sleep(0.05)

    bridge = Bridge()
    bridge._window = webview.create_window(
        "PixSift", settings.url, js_api=bridge, width=1320, height=860, min_size=(900, 600),
    )
    webview.start(private_mode=False)  # keep localStorage (viewer preferences) between launches
    server.should_exit = True
    thread.join(timeout=5)


if __name__ == "__main__":
    main()
