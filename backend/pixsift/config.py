"""Application settings. Override any value with a PIXSIFT_* environment variable."""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
)

# Directory names never descended into (system, caches, dev trees).
SKIP_DIR_NAMES = frozenset(
    {"node_modules", "__pycache__", "Library", "AppData", "$RECYCLE.BIN", "System Volume Information"}
)

# Directory suffixes that are app bundles / managed libraries, not user folders.
# Photos/Lightroom libraries hold thousands of derivatives that would show up as duplicates.
SKIP_DIR_SUFFIXES = (".app", ".photoslibrary", ".lrdata", ".photosLibrary", ".aplibrary")


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("PIXSIFT_DATA_DIR") or user_data_dir("PixSift", appauthor=False))
    )
    host: str = os.environ.get("PIXSIFT_HOST", "127.0.0.1")
    port: int = int(os.environ.get("PIXSIFT_PORT", "8765"))
    thumb_size: int = 320
    min_file_bytes: int = int(os.environ.get("PIXSIFT_MIN_BYTES", "10000"))  # skip icons / tiny sprites
    workers: int = max(2, (os.cpu_count() or 4) - 1)
    # Per-launch access token (see security.py). Set PIXSIFT_TOKEN to keep one fixed, e.g. for UI development.
    token: str = field(default_factory=lambda: os.environ.get("PIXSIFT_TOKEN") or secrets.token_urlsafe(32))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pixsift.db"

    @property
    def models_dir(self) -> Path:
        return Path(os.environ.get("PIXSIFT_MODELS_DIR") or self.data_dir / "models")

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    def ensure_dirs(self) -> None:
        # Owner-only: the library holds face data and thumbnails of private pictures.
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            self.data_dir.chmod(0o700)  # also tighten folders created by older versions
        self.thumbs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?token={self.token}"
