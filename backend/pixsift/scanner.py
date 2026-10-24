"""Folder walking: find image files, pruning hidden/system/bundle folders."""

import os
import stat
from collections.abc import Iterator

from .config import IMAGE_EXTENSIONS, SKIP_DIR_NAMES, SKIP_DIR_SUFFIXES


# The stat module defines these constants everywhere, but only Windows reports st_file_attributes.
_WIN_HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM if os.name == "nt" else 0


def _hidden_on_windows(path: str) -> bool:
    """Windows marks hidden/system folders with attributes rather than a leading dot."""
    if not _WIN_HIDDEN:
        return False
    try:
        return bool(os.stat(path, follow_symlinks=False).st_file_attributes & _WIN_HIDDEN)
    except OSError:
        return True  # unreadable: skip


def iter_images(root: str, min_bytes: int) -> Iterator[tuple[str, int, float]]:
    """Yield (path, size, mtime) for image files under root, pruning hidden/system/bundle dirs."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d.lower() not in SKIP_DIR_NAMES and not d.lower().endswith(SKIP_DIR_SUFFIXES)
            and not _hidden_on_windows(os.path.join(dirpath, d))
        ]
        for name in filenames:
            if name.startswith(".") or os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size >= min_bytes:
                yield path, st.st_size, st.st_mtime
