"""Background job: download models -> scan folders -> analyse new pictures -> group faces.

One job runs at a time. Every phase is incremental, so re-running only does the new work.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
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
ANALYZE_TIMEOUT = 120.0  # seconds per batch before stuck pictures are skipped


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
    analyze_started: float | None = None
    current_file: str | None = None
    timeouts: int = 0  # pictures skipped because analysis hung
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
                        self._analyze_pending()
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
                # One thread per inference: the pipeline already analyses several pictures in parallel.
                self._analyzer = Analyzer(self.models, threads=1)
            return self._analyzer

    # Pictures waiting for analysis, skipping those on drives that aren't connected (they wait for the drive).
    _PENDING_WHERE = (
        "i.analyzed_at IS NULL AND i.missing=0 AND i.thumb IS NOT NULL "
        "AND (i.volume_id IS NULL OR EXISTS (SELECT 1 FROM volumes v WHERE v.id=i.volume_id AND v.mounted=1))"
    )

    def _analyze_pending(self) -> None:
        total = self.db.query_one(f"SELECT COUNT(*) AS n FROM images i WHERE {self._PENDING_WHERE}")["n"]
        self._set(phase="analyzing", to_analyze=total, analyzed=0, analyze_started=time.time())
        if not total:
            return
        analyzer = self.analyzer()
        # Own pool, never waited on after a hang: a stuck worker thread can't block the job from finishing.
        pool = ThreadPoolExecutor(max_workers=self.settings.workers, thread_name_prefix="pixsift-analyze")
        last_id = 0
        while not self._cancel.is_set():
            rows = self.db.query(
                "SELECT i.id, i.path, i.filename, i.camera_make, i.edited_from FROM images i "
                f"WHERE {self._PENDING_WHERE} AND i.id > ? ORDER BY i.id LIMIT ?", (last_id, _ANALYZE_BATCH))
            if not rows:
                break
            last_id = rows[-1]["id"]
            self._set(current_file=rows[0]["path"])
            futures = [pool.submit(_safe_analyze, analyzer, r) for r in rows]
            deadline = time.time() + ANALYZE_TIMEOUT
            timed_out = False
            for row, fut in zip(rows, futures):
                try:
                    result = fut.result(timeout=max(0.0, deadline - time.time()))
                except FutureTimeout:
                    # A picture hung the decoder/model (or its drive stopped responding). Skip it and carry on;
                    # threads can't be killed, so the stuck one is abandoned and a fresh pool takes over.
                    timed_out = True
                    self._bump(timeouts=1)
                    self._record_failure(row, "analysis timed out")
                    continue
                if result is _SKIP:
                    continue  # file not reachable right now (drive unplugged/asleep): retry on a later run
                try:
                    apply_analysis(self.db, self.settings.thumbs_dir, row, result)
                except Exception as exc:  # one bad picture must never stop the whole job
                    self._record_failure(row, f"{type(exc).__name__}: {exc}")
            self._bump(analyzed=len(rows))
            if timed_out:
                pool.shutdown(wait=False, cancel_futures=True)
                pool = ThreadPoolExecutor(max_workers=self.settings.workers, thread_name_prefix="pixsift-analyze")
        pool.shutdown(wait=not self.status.timeouts, cancel_futures=True)
        self._set(current_file=None)

    def _record_failure(self, row: dict, message: str) -> None:
        self.db.execute("UPDATE images SET analyzed_at=datetime('now'), error=COALESCE(error, ?) WHERE id=?",
                        (message[:500], row["id"]))

    def analyze_now(self, image_id: int) -> None:
        """Synchronous re-analysis of one picture (after an edit)."""
        row = self.db.query_one(
            "SELECT id, path, filename, camera_make, edited_from FROM images WHERE id=?", (image_id,)
        )
        if row:
            result = _safe_analyze(self.analyzer(), row)
            if result is not _SKIP:
                apply_analysis(self.db, self.settings.thumbs_dir, row, result)


_SKIP = object()  # "couldn't reach the file right now": leave it pending


def _safe_analyze(analyzer: Analyzer, row: dict) -> AnalysisResult | None | object:
    if not os.path.exists(row["path"]):
        return _SKIP
    try:
        return analyzer.analyze(row["path"], filename=row["filename"], camera=bool(row["camera_make"]))
    except Exception:
        if not os.path.exists(row["path"]):
            return _SKIP  # the drive went away mid-read
        return None  # corrupt/unsupported: recorded as analysed so it isn't retried forever


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
