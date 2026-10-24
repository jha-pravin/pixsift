"""Folder walking: find image files, pruning hidden/system/bundle folders."""

import os
from collections.abc import Iterator

from .config import IMAGE_EXTENSIONS, SKIP_DIR_NAMES, SKIP_DIR_SUFFIXES


def iter_images(root: str, min_bytes: int) -> Iterator[tuple[str, int, float]]:
    """Yield (path, size, mtime) for image files under root, pruning hidden/system/bundle dirs."""
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in SKIP_DIR_NAMES and not d.endswith(SKIP_DIR_SUFFIXES)
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
