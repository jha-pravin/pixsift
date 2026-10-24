"""Browser mode: run the engine and open the UI in the default browser."""

import os
import threading
import webbrowser

import uvicorn

from .api import create_app
from .config import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    print(f"PixSift data: {settings.data_dir}")
    print(f"Open PixSift: {settings.url}")
    if not os.environ.get("PIXSIFT_NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, (settings.url,)).start()  # once the server is listening
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
