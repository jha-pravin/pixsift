"""Background job: download models -> scan folders -> analyse new pictures -> group faces.

One job runs at a time. Every phase is incremental, so re-running only does the new work.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import faces as face_ops
from .analyzer import AnalysisResult, Analyzer, save_crop
from .config import Settings
from .db import Database, like_prefix
from .media import process_file
from .models import ModelStore
from .scanner import iter_images

_SCAN_BATCH = 200
_ANALYZE_BATCH = 32


@dataclass
class JobStatus:
    state: str = "idle"  # idle | running | done | cancelled | error
    phase: str | None = None  # models | scanning | analyzing | grouping
    roots: list[str] = field(default_factory=list)
    current_root: str | None = None
    found: int = 0
    processed: int = 0
    unchanged: int = 0
    errors: int = 0
    missing: int = 0
    offline_roots: int = 0  # folders skipped because their drive isn't connected
    to_analyze: int = 0
    analyzed: int = 0
    auto_named: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    message: str | None = None


class Pipeline:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.models = ModelStore(settings.models_dir)
        self.status = JobStatus()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._analyzer: Analyzer | None = None
        self._analyzer_lock = threading.Lock()

    # ---- control ----------------------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            status = asdict(self.status)
        new_drives = self.db.query("SELECT id, label, mount FROM volumes WHERE mounted=1 AND status='new'")
        return {**status, "models": self.models.status(), "new_drives": new_drives}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, roots: list[str] | None = None, analyze: bool = True) -> bool:
        """roots=None skips scanning (analyse + group only)."""
        if self.running:
            return False
        self._cancel.clear()
        with self._lock:
            self.status = JobStatus(state="running", roots=roots or [], started_at=time.time())
        self._thread = threading.Thread(target=self._run, args=(roots, analyze), daemon=True, name="pixsift-job")
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _set(self, **values) -> None:
        with self._lock:
            for k, v in values.items():
                setattr(self.status, k, v)

    def _bump(self, **deltas: int) -> None:
        with self._lock:
            for k, v in deltas.items():
                setattr(self.status, k, getattr(self.status, k) + v)

    def _run(self, roots: list[str] | None, analyze: bool) -> None:
        try:
            with ThreadPoolExecutor(max_workers=self.settings.workers, thread_name_prefix="pixsift-work") as pool:
                for root in roots or []:
                    if self._cancel.is_set():
                        break
                    self._set(phase="scanning", current_root=root)
                    self._scan_root(root, pool)
                self._set(current_root=None)
                if analyze and not self._cancel.is_set():
                    self._set(phase="models")
                    self.models.ensure(self._cancel)
                    if not self._cancel.is_set():
                        self._analyze_pending(pool)
                if analyze and not self._cancel.is_set():
                    self._set(phase="grouping")
                    self._set(auto_named=face_ops.auto_assign(self.db))  # known people first...
                    face_ops.recluster(self.db)                           # ...then group the rest
            final = "cancelled" if self._cancel.is_set() else "done"
        except Exception as exc:
            final = "error"
            self._set(message=f"{type(exc).__name__}: {exc}")
        self._set(state=final, phase=None, current_root=None, finished_at=time.time())

    # ---- scanning ---------------------------------------------------------------------------------

    def _scan_root(self, root: str, pool: ThreadPoolExecutor) -> None:
        s = self.settings
        if not os.path.isdir(root):
            # Unplugged drive (or folder gone): keep its pictures as they are instead of marking them deleted.
            self._bump(offline_roots=1)
            return
        volume = self.db.volume_for(root)
        volume_id = volume["id"] if volume else None
        known = self.db.known_files(root)
        seen: set[str] = set()
        pending, unchanged = [], []

        def flush() -> None:
            recs = list(pool.map(lambda a: process_file(*a, s.thumbs_dir, s.thumb_size), pending))
            for r in recs:
                r["volume_id"] = volume_id
            self.db.upsert_images(recs)
            self._bump(processed=len(recs), errors=sum(1 for r in recs if r["error"]))
            pending.clear()

        for path, size, mtime in iter_images(root, s.min_file_bytes):
            if self._cancel.is_set():
                return
            seen.add(path)
            self._bump(found=1)
            if known.get(path) == (size, mtime):
                unchanged.append(path)
                continue
            pending.append((path, size, mtime))
            if len(pending) >= _SCAN_BATCH:
                flush()
        if pending:
            flush()
        self.db.touch_present(unchanged)
        gone = known.keys() - seen
        self.db.set_missing(gone)
        self._bump(unchanged=len(unchanged), missing=len(gone))
        self.db.record_root(root, volume_id)
        if volume_id:
            self.db.execute("UPDATE volumes SET status='tracked', last_scanned=datetime('now') WHERE id=?", (volume_id,))
            self.db.execute("UPDATE images SET volume_id=? WHERE volume_id IS NULL AND path LIKE ? ESCAPE '\\'",
                            (volume_id, like_prefix(root)))  # pictures indexed before drive tracking existed

    # ---- analysis ---------------------------------------------------------------------------------

    def analyzer(self) -> Analyzer:
        with self._analyzer_lock:
            if self._analyzer is None:
                self.models.ensure()
                self._analyzer = Analyzer(self.models, threads=2)
            return self._analyzer

    _PENDING_SQL = (
        "SELECT id, path, filename, camera_make, edited_from FROM images "
        "WHERE analyzed_at IS NULL AND missing=0 AND thumb IS NOT NULL AND id > ? ORDER BY id LIMIT ?"
    )

    def _analyze_pending(self, pool: ThreadPoolExecutor) -> None:
        total = self.db.query_one(
            "SELECT COUNT(*) AS n FROM images WHERE analyzed_at IS NULL AND missing=0 AND thumb IS NOT NULL"
        )["n"]
        self._set(phase="analyzing", to_analyze=total, analyzed=0)
        if not total:
            return
        analyzer = self.analyzer()
        last_id = 0
        while not self._cancel.is_set():
            rows = self.db.query(self._PENDING_SQL, (last_id, _ANALYZE_BATCH))
            if not rows:
                break
            last_id = rows[-1]["id"]
            for row, result in zip(rows, pool.map(lambda r: _safe_analyze(analyzer, r), rows)):
                apply_analysis(self.db, self.settings.thumbs_dir, row, result)
            self._bump(analyzed=len(rows))

    def analyze_now(self, image_id: int) -> None:
        """Synchronous re-analysis of one picture (after an edit)."""
        row = self.db.query_one(
            "SELECT id, path, filename, camera_make, edited_from FROM images WHERE id=?", (image_id,)
        )
        if row:
            apply_analysis(self.db, self.settings.thumbs_dir, row, _safe_analyze(self.analyzer(), row))


def _safe_analyze(analyzer: Analyzer, row: dict) -> AnalysisResult | None:
    try:
        return analyzer.analyze(row["path"], filename=row["filename"], camera=bool(row["camera_make"]))
    except Exception:
        return None  # unreadable now (moved/corrupt); recorded as analysed so it isn't retried forever


def apply_analysis(db: Database, thumbs_dir: Path, row: dict, result: AnalysisResult | None) -> None:
    image_id = row["id"]
    old = db.query("SELECT id, embedding, person_id, crop FROM faces WHERE image_id=?", (image_id,))
    refs = [f for f in old if f["person_id"]]
    if row.get("edited_from"):
        refs += db.query(
            "SELECT embedding, person_id FROM faces WHERE image_id=? AND person_id IS NOT NULL", (row["edited_from"],)
        )
    for f in old:
        if f["crop"]:
            (thumbs_dir / f["crop"]).unlink(missing_ok=True)

    with db.conn() as c:
        c.execute("DELETE FROM faces WHERE image_id=?", (image_id,))
        if result is None:
            c.execute("UPDATE images SET analyzed_at=datetime('now'), face_count=0 WHERE id=?", (image_id,))
            return
        people = face_ops.carry_over([f.embedding for f in result.faces], refs)
        for n, (face, person_id) in enumerate(zip(result.faces, people)):
            crop = f"faces/{image_id % 256:02x}/{image_id}_{n}_{int(time.time())}.webp"
            save_crop(face.crop, thumbs_dir, crop)
            c.execute(
                "INSERT INTO faces(image_id, x, y, w, h, score, embedding, crop, person_id, assigned_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (image_id, *face.box, face.score, face_ops.to_blob(face.embedding), crop,
                 person_id, "carry" if person_id else None),
            )
        c.execute(
            "UPDATE images SET analyzed_at=datetime('now'), face_count=?, clip_scores=?, clip_embedding=?, "
            "category=CASE WHEN category_locked=1 THEN category ELSE ? END WHERE id=?",
            (len(result.faces), json.dumps(result.scores), result.clip_embedding.tobytes(), result.category, image_id),
        )
