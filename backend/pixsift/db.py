"""SQLite storage. One connection per thread; WAL lets the API read while a scan writes."""

import os
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# Each entry upgrades the schema by one version (tracked in PRAGMA user_version). Never edit old entries.
MIGRATIONS = [
"""
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    folder        TEXT NOT NULL,
    filename      TEXT NOT NULL,
    ext           TEXT NOT NULL,
    size          INTEGER NOT NULL,
    mtime         REAL NOT NULL,
    quick_hash    TEXT,
    width         INTEGER,
    height        INTEGER,
    taken_at      TEXT,
    camera_make   TEXT,
    camera_model  TEXT,
    gps_lat       REAL,
    gps_lon       REAL,
    has_exif      INTEGER NOT NULL DEFAULT 0,
    date_source   TEXT,               -- 'exif' or 'file' (mtime fallback)
    thumb         TEXT,
    error         TEXT,
    missing       INTEGER NOT NULL DEFAULT 0,
    scanned_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_images_folder   ON images(folder);
CREATE INDEX IF NOT EXISTS ix_images_hash     ON images(quick_hash);
CREATE INDEX IF NOT EXISTS ix_images_taken_at ON images(taken_at);

CREATE TABLE IF NOT EXISTS scan_roots (
    path          TEXT PRIMARY KEY,
    last_scanned  TEXT
);
""",
"""
ALTER TABLE images ADD COLUMN analyzed_at      TEXT;
ALTER TABLE images ADD COLUMN category         TEXT;   -- primary: document | screenshot | photo | graphic
ALTER TABLE images ADD COLUMN clip_scores      TEXT;   -- JSON {category: probability}
ALTER TABLE images ADD COLUMN clip_embedding   BLOB;   -- float16[512], kept for re-classification/search
ALTER TABLE images ADD COLUMN category_locked  INTEGER NOT NULL DEFAULT 0;  -- set by the user; analysis keeps it
ALTER TABLE images ADD COLUMN face_count       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE images ADD COLUMN edited_from      INTEGER REFERENCES images(id);
CREATE INDEX ix_images_category ON images(category);
CREATE INDEX ix_images_faces    ON images(face_count) WHERE face_count > 0;
CREATE INDEX ix_images_pending  ON images(analyzed_at) WHERE analyzed_at IS NULL;

-- Free-form user tags ("holiday", "passport", ...).
CREATE TABLE tags (
    image_id  INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (image_id, tag)
);
CREATE INDEX ix_tags_tag ON tags(tag);

CREATE TABLE persons (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cover_face_id INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE faces (
    id           INTEGER PRIMARY KEY,
    image_id     INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,  -- normalised 0..1, display orientation
    score        REAL NOT NULL,
    embedding    BLOB NOT NULL,           -- float32[128], L2-normalised
    crop         TEXT,                    -- face thumbnail, relative to thumbs dir
    cluster_id   INTEGER,                 -- unnamed group from the last clustering run
    person_id    INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    assigned_by  TEXT,                    -- 'user' | 'carry' (kept across re-analysis / edits)
    ignored      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_faces_image   ON faces(image_id);
CREATE INDEX ix_faces_person  ON faces(person_id);
CREATE INDEX ix_faces_cluster ON faces(cluster_id);

-- "Not this person": stops suggestions from proposing the same match again.
CREATE TABLE face_rejections (
    face_id   INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    PRIMARY KEY (face_id, person_id)
);
""",
]

IMAGE_COLUMNS = (
    "path", "folder", "filename", "ext", "size", "mtime", "quick_hash", "width", "height",
    "taken_at", "camera_make", "camera_model", "gps_lat", "gps_lon", "has_exif", "date_source", "thumb", "error",
)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        self._migrate()

    def _migrate(self) -> None:
        c = self.conn()
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            c.executescript(f"BEGIN;\n{script}\nPRAGMA user_version={i};\nCOMMIT;")

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, tuple(params))]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self.conn().execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def upsert_images(self, records: list[Mapping[str, Any]]) -> None:
        if not records:
            return
        cols = ", ".join(IMAGE_COLUMNS)
        marks = ", ".join(f":{c}" for c in IMAGE_COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in IMAGE_COLUMNS if c != "path")
        sql = (
            f"INSERT INTO images ({cols}) VALUES ({marks}) "
            f"ON CONFLICT(path) DO UPDATE SET {updates}, missing=0, analyzed_at=NULL, "
            "scanned_at=datetime('now')"
        )
        with self.conn() as c:
            c.executemany(sql, records)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.conn() as c:
            return c.execute(sql, tuple(params))

    def known_files(self, root: str) -> dict[str, tuple[int, float]]:
        """path -> (size, mtime) for every indexed file under root (only the columns needed)."""
        rows = self.conn().execute(
            "SELECT path, size, mtime FROM images WHERE path = ? OR path LIKE ? ESCAPE '\\'",
            (root, _like_prefix(root)),
        )
        return {r[0]: (r[1], r[2]) for r in rows}

    def set_missing(self, paths: Iterable[str]) -> None:
        with self.conn() as c:
            c.executemany("UPDATE images SET missing=1 WHERE path=?", ((p,) for p in paths))

    def touch_present(self, paths: Iterable[str]) -> None:
        with self.conn() as c:
            c.executemany("UPDATE images SET missing=0 WHERE path=? AND missing=1", ((p,) for p in paths))

    def record_root(self, root: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO scan_roots(path, last_scanned) VALUES (?, datetime('now')) "
                "ON CONFLICT(path) DO UPDATE SET last_scanned=excluded.last_scanned",
                (root,),
            )


def _like_prefix(root: str) -> str:
    """LIKE pattern matching everything strictly inside `root`."""
    base = root.rstrip("/\\") + os.sep
    return base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
