"""External drives: detect them, recognise them again at any mount point, re-scan them when connected.

A drive is identified by a stable OS volume ID (macOS VolumeUUID, Windows volume serial number), not by its
mount path, so "/Volumes/Photos" vs "/Volumes/Photos 1", or E: vs F:, is still the same drive. When a known
drive shows up at a new place, the stored paths of its pictures are rewritten to the new mount point.

While a drive is disconnected, its pictures stay in the library (thumbnails, faces, names) and are shown as
"offline" rather than deleted.
"""

import getpass
import os
import plistlib
import string
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .db import Database, like_prefix

POLL_SECONDS = 5


@dataclass(frozen=True)
class Mount:
    uid: str
    label: str
    path: str


# ---- detection ------------------------------------------------------------------------------------

_mac_cache: dict[tuple[str, int], str | None] = {}  # (path, st_dev) -> uid; st_dev changes on remount


def _mac_uid(path: str) -> str | None:
    try:
        key = (path, os.stat(path).st_dev)
    except OSError:
        return None
    if key not in _mac_cache:
        try:
            out = subprocess.run(["diskutil", "info", "-plist", path], capture_output=True, timeout=10, check=True).stdout
            info = plistlib.loads(out)
            _mac_cache[key] = info.get("VolumeUUID") or info.get("DiskUUID")
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
            _mac_cache[key] = None  # network shares, odd mounts: not tracked
    return _mac_cache[key]


def _list_mac() -> list[Mount]:
    out = []
    try:
        names = os.listdir("/Volumes")
    except OSError:
        return out
    for name in names:
        path = os.path.join("/Volumes", name)
        if name.startswith(".") or os.path.islink(path) or not os.path.isdir(path):
            continue  # the boot disk appears as a symlink to /
        uid = _mac_uid(path)
        if uid:
            out.append(Mount(f"mac:{uid}", name, path))
    return out


def _list_windows() -> list[Mount]:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    system = os.environ.get("SystemDrive", "C:").upper()
    out = []
    mask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        root = f"{letter}:\\"
        if not mask & (1 << i) or f"{letter}:" == system:
            continue
        if kernel32.GetDriveTypeW(root) not in (2, 3):  # removable or fixed (USB hard drives report fixed)
            continue
        label = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        if kernel32.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), None, None, None, 0):
            out.append(Mount(f"win:{serial.value:08X}", label.value or f"Drive {letter}", root))
    return out


def _list_linux() -> list[Mount]:
    user = getpass.getuser()
    out = []
    for base in (f"/media/{user}", f"/run/media/{user}"):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            path = os.path.join(base, name)
            if os.path.ismount(path):
                out.append(Mount(f"linux:{name}", name, path))  # label-based: the mount dir is the label
    return out


def list_mounted() -> list[Mount]:
    if sys.platform == "darwin":
        return _list_mac()
    if sys.platform == "win32":
        return _list_windows()
    return _list_linux()


# ---- watching -------------------------------------------------------------------------------------

def _remap(db: Database, volume_id: int, old: str, new: str) -> None:
    """The drive is mounted somewhere else now: rewrite the stored paths of everything on it."""
    old_b, new_b = old.rstrip("/\\"), new.rstrip("/\\")
    n = len(old_b) + 1
    pattern = like_prefix(old_b)
    with db.conn() as c:
        for table, col in (("images", "path"), ("images", "folder"), ("scan_roots", "path")):
            c.execute(
                f"UPDATE {table} SET {col} = ? || substr({col}, ?) "
                f"WHERE volume_id=? AND ({col} = ? OR {col} LIKE ? ESCAPE '\\')",
                (new_b, n, volume_id, old_b, pattern),
            )


class DriveWatcher:
    """Polls for connected drives. Known drives are re-scanned when they appear; new ones wait for the user."""

    def __init__(self, db: Database, start_scan: Callable[[list[str]], bool],
                 lister: Callable[[], list[Mount]] = list_mounted):
        self.db = db
        self.start_scan = start_scan
        self.lister = lister
        self._pending: set[int] = set()  # drives to scan once the current job finishes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="pixsift-drives")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync()
            except Exception:
                pass  # a flaky drive must never take the watcher down
            self._stop.wait(POLL_SECONDS)

    def sync(self) -> None:
        with self._lock:
            mounts = {m.uid: m for m in self.lister()}
            known = {r["uid"]: r for r in self.db.query("SELECT * FROM volumes")}
            for uid, m in mounts.items():
                row = known.get(uid)
                if row is None:
                    self.db.execute(
                        "INSERT INTO volumes(uid, label, mount, mounted, last_seen) VALUES (?, ?, ?, 1, datetime('now'))",
                        (uid, m.label, m.path),
                    )
                    continue
                if row["mount"] != m.path:
                    _remap(self.db, row["id"], row["mount"], m.path)
                self.db.execute(
                    "UPDATE volumes SET mounted=1, mount=?, label=?, last_seen=datetime('now') WHERE id=?",
                    (m.path, m.label, row["id"]),
                )
                if not row["mounted"] and row["status"] == "tracked" and row["auto_scan"]:
                    self._pending.add(row["id"])
            gone = [r["id"] for uid, r in known.items() if r["mounted"] and uid not in mounts]
            for vid in gone:
                self.db.execute("UPDATE volumes SET mounted=0 WHERE id=?", (vid,))
                self._pending.discard(vid)
            self._run_pending()

    def _run_pending(self) -> None:
        for vid in list(self._pending):
            roots = [r["path"] for r in self.db.query(
                "SELECT s.path FROM scan_roots s JOIN volumes v ON v.id=s.volume_id WHERE v.id=? AND v.mounted=1",
                (vid,))]
            if not roots:
                self._pending.discard(vid)
            elif self.start_scan(roots):
                self._pending.discard(vid)
            else:
                break  # a job is running; try again next poll

    def track(self, volume_id: int) -> list[str]:
        """User said yes to a drive: remember it and return the folders to scan (the whole drive by default)."""
        v = self.db.query_one("SELECT * FROM volumes WHERE id=?", (volume_id,))
        if not v:
            return []
        self.db.execute("UPDATE volumes SET status='tracked' WHERE id=?", (volume_id,))
        roots = [r["path"] for r in self.db.query("SELECT path FROM scan_roots WHERE volume_id=?", (volume_id,))]
        return roots or [v["mount"]]
