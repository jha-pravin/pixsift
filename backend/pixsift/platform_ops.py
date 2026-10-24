"""OS integration: reveal a file in Finder/Explorer, open with the default app."""

import os
import subprocess
import sys


def reveal_in_folder(path: str) -> None:
    """Open the containing folder with `path` selected."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform == "win32":
        # explorer wants a single "/select,<path>" argument; it returns exit code 1 even on success.
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    else:
        # Most Linux file managers lack a portable "select" flag; open the folder instead.
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_default(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_label() -> str:
    return {"darwin": "Show in Finder", "win32": "Show in Explorer"}.get(sys.platform, "Show in folder")
