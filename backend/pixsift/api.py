"""HTTP API consumed by the UI. Binds to localhost only; files are served by id, never by raw path."""

import io
from contextlib import asynccontextmanager
import json
import os
import string
import sys
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, platform_ops
from .config import Settings
from .db import Database
from .deps import MUTATING
from .editor import EditRequest, apply_edit
from .media import process_file
from .people_api import router as people_router
from .faces import ask_min_photos
from .pipeline import Pipeline
from .security import AccessGuard
from .volumes import DriveWatcher

BROWSER_NATIVE = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
PREVIEW_MAX = 2048
SORTS = {
    "taken_desc": "i.taken_at DESC, i.id DESC",
    "taken_asc": "i.taken_at ASC, i.id ASC",
    "name": "i.filename COLLATE NOCASE ASC, i.id ASC",
    "size_desc": "i.size DESC, i.id DESC",
}
LIST_COLUMNS = (
    "i.id, i.path, i.folder, i.filename, i.ext, i.size, i.width, i.height, i.taken_at, i.date_source, "
    "i.thumb, i.error, i.missing, i.category, i.face_count, i.camera_model, i.volume_id, "
    "COALESCE(v.mounted = 0, 0) AS offline, v.label AS drive"
)


class ScanRequest(BaseModel):
    roots: list[str]
    analyze: bool = True


class CategoryRequest(BaseModel):
    category: Literal["document", "screenshot", "photo", "graphic"] | None  # None = back to automatic


class TagRequest(BaseModel):
    tag: str


class DriveUpdate(BaseModel):
    auto_scan: bool


class SettingsUpdate(BaseModel):
    ask_min_photos: int = Field(ge=2, le=100)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    db = Database(settings.db_path)
    pipeline = Pipeline(db, settings)
    watcher = DriveWatcher(db, lambda roots: pipeline.start(roots))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.watch_drives:
            watcher.start()
        # Resume analysis that was interrupted (app quit, laptop slept, drive unplugged) without waiting
        # for the next scan.
        if pipeline.models.status()["ready"] and db.query_one(
            f"SELECT 1 FROM images i WHERE {Pipeline._PENDING_WHERE} LIMIT 1"
        ):
            pipeline.start(None)
        yield
        watcher.stop()

    app = FastAPI(title="PixSift", version=__version__, lifespan=lifespan)
    app.state.db, app.state.pipeline, app.state.settings, app.state.watcher = db, pipeline, settings, watcher
    # Starlette runs the last-added middleware first: Host check (DNS rebinding), then the access guard.
    app.add_middleware(AccessGuard, token=settings.token)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.include_router(people_router, prefix="/api")

    def get_image(image_id: int) -> dict:
        row = db.query_one("SELECT * FROM images WHERE id=?", (image_id,))
        if not row:
            raise HTTPException(404, "image not found")
        return row

    def existing_file(row: dict) -> str:
        if not os.path.isfile(row["path"]):
            drive = row.get("volume_id") and db.query_one(
                "SELECT label FROM volumes WHERE id=? AND mounted=0", (row["volume_id"],))
            if drive:
                raise HTTPException(409, f"Connect the drive “{drive['label']}” to open this picture")
            raise HTTPException(410, "file no longer exists on disk")
        return row["path"]

    # ---- app / jobs -------------------------------------------------------------------------------

    @app.get("/api/health")
    def health():
        return {"version": __version__, "platform": sys.platform, "reveal_label": platform_ops.reveal_label()}

    @app.get("/api/stats")
    def stats():
        totals = db.query_one(
            "SELECT COUNT(*) AS total, COALESCE(SUM(error IS NOT NULL), 0) AS errors, "
            "COALESCE(SUM(size), 0) AS bytes, COUNT(DISTINCT folder) AS folders, "
            "COALESCE(SUM(analyzed_at IS NULL AND thumb IS NOT NULL), 0) AS pending "
            "FROM images WHERE missing=0"
        )
        dupes = db.query_one(
            "SELECT COUNT(*) AS groups, COALESCE(SUM(n - 1), 0) AS extra FROM "
            "(SELECT COUNT(*) AS n FROM images WHERE quick_hash IS NOT NULL AND missing=0 "
            "GROUP BY quick_hash HAVING n > 1)"
        )
        people = db.query_one(
            "SELECT (SELECT COUNT(*) FROM persons WHERE hidden=0) AS people, "
            "(SELECT COUNT(DISTINCT cluster_id) FROM faces WHERE cluster_id IS NOT NULL AND person_id IS NULL "
            " AND ignored=0) AS unnamed_groups, "
            "(SELECT COUNT(*) FROM faces f JOIN persons p ON p.id=f.person_id "
            " WHERE f.assigned_by='auto' AND p.hidden=0) AS auto_named, "
            "(SELECT COUNT(*) FROM volumes WHERE status='tracked') AS drives"
        )
        return {**totals, **people, "duplicate_groups": dupes["groups"], "duplicate_files": dupes["extra"]}

    @app.get("/api/dashboard")
    def dashboard():
        cats = []
        for key in ("people", "photo", "document", "screenshot", "graphic"):
            where = "face_count > 0" if key == "people" else "category = ?"
            params = () if key == "people" else (key,)
            n = db.query_one(f"SELECT COUNT(*) AS n FROM images WHERE missing=0 AND {where}", params)["n"]
            samples = db.query(
                f"SELECT id FROM images WHERE missing=0 AND {where} ORDER BY taken_at DESC LIMIT 4", params
            )
            cats.append({"key": key, "count": n, "samples": [s["id"] for s in samples]})
        recent = db.query(
            "SELECT id FROM images WHERE missing=0 AND thumb IS NOT NULL ORDER BY taken_at DESC LIMIT 12"
        )
        return {"categories": cats, "recent": [r["id"] for r in recent], "stats": stats()}

    @app.get("/api/roots")
    def roots():
        return db.query("SELECT path, last_scanned FROM scan_roots ORDER BY path")

    @app.get("/api/suggested-roots")
    def suggested_roots():
        home = Path.home()
        out = [{"path": str(home / n), "label": n}
               for n in ("Pictures", "Desktop", "Downloads", "Documents") if (home / n).is_dir()]
        out.append({"path": str(home), "label": "Home folder"})
        if sys.platform == "darwin" and os.path.isdir("/Volumes"):
            for v in sorted(os.listdir("/Volumes")):
                p = os.path.join("/Volumes", v)
                if not os.path.islink(p) and os.path.isdir(p):  # the boot disk is a symlink to /
                    out.append({"path": p, "label": f"Drive: {v}"})
        elif sys.platform == "win32":
            for letter in string.ascii_uppercase:
                if os.path.isdir(f"{letter}:\\"):
                    out.append({"path": f"{letter}:\\", "label": f"Drive {letter}:"})
        return out

    @app.post("/api/scan", dependencies=MUTATING)
    def start_scan(req: ScanRequest):
        roots = [os.path.abspath(os.path.expanduser(r.strip())) for r in req.roots if r.strip()]
        bad = [r for r in roots if not os.path.isdir(r)]
        if not roots or bad:
            raise HTTPException(400, f"not a directory: {', '.join(bad) or '(none given)'}")
        if settings.watch_drives:
            watcher.sync()  # so pictures on a just-connected drive are linked to it
        if not pipeline.start(roots, analyze=req.analyze):
            raise HTTPException(409, "a job is already running")
        return pipeline.snapshot()

    # ---- drives -----------------------------------------------------------------------------------

    @app.get("/api/drives")
    def drives():
        return db.query(
            "SELECT v.id, v.label, v.mount, v.mounted, v.status, v.auto_scan, v.last_seen, v.last_scanned, "
            "(SELECT COUNT(*) FROM images i WHERE i.volume_id=v.id AND i.missing=0) AS pictures "
            "FROM volumes v WHERE v.status<>'ignored' OR v.mounted=1 ORDER BY v.mounted DESC, v.label"
        )

    def get_drive(drive_id: int) -> dict:
        row = db.query_one("SELECT * FROM volumes WHERE id=?", (drive_id,))
        if not row:
            raise HTTPException(404, "drive not found")
        return row

    @app.post("/api/drives/{drive_id}/scan", dependencies=MUTATING)
    def scan_drive(drive: dict = Depends(get_drive)):
        if not drive["mounted"]:
            raise HTTPException(409, f"Connect the drive “{drive['label']}” first")
        if not pipeline.start(watcher.track(drive["id"])):
            raise HTTPException(409, "a job is already running")
        return pipeline.snapshot()

    @app.post("/api/drives/{drive_id}/ignore", dependencies=MUTATING)
    def ignore_drive(drive: dict = Depends(get_drive)):
        db.execute("UPDATE volumes SET status='ignored' WHERE id=?", (drive["id"],))
        return {"ok": True}

    @app.patch("/api/drives/{drive_id}", dependencies=MUTATING)
    def update_drive(req: DriveUpdate, drive: dict = Depends(get_drive)):
        db.execute("UPDATE volumes SET auto_scan=? WHERE id=?", (int(req.auto_scan), drive["id"]))
        return {"ok": True}

    # ---- settings ---------------------------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings():
        return {"ask_min_photos": ask_min_photos(db)}

    @app.put("/api/settings", dependencies=MUTATING)
    def put_settings(req: SettingsUpdate):
        db.set_setting("ask_min_photos", str(req.ask_min_photos))
        return get_settings()

    @app.post("/api/analyze", dependencies=MUTATING)
    def start_analyze():
        if not pipeline.start(None):
            raise HTTPException(409, "a job is already running")
        return pipeline.snapshot()

    @app.get("/api/job")
    def job_status():
        return pipeline.snapshot()

    @app.post("/api/job/cancel", dependencies=MUTATING)
    def cancel_job():
        pipeline.cancel()
        return pipeline.snapshot()

    # ---- browsing ---------------------------------------------------------------------------------

    @app.get("/api/folders")
    def folders():
        return db.query(
            "SELECT folder, COUNT(*) AS count FROM images WHERE missing=0 GROUP BY folder ORDER BY folder"
        )

    @app.get("/api/tags")
    def tags():
        return db.query(
            "SELECT t.tag, COUNT(*) AS count FROM tags t JOIN images i ON i.id=t.image_id "
            "WHERE i.missing=0 GROUP BY t.tag ORDER BY t.tag COLLATE NOCASE"
        )

    @app.get("/api/images")
    def list_images(
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        category: Literal["document", "screenshot", "photo", "graphic", "people", "unsorted"] | None = None,
        person: list[int] = Query(default=[]),
        tag: str | None = None,
        folder: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        duplicates: bool = False,
        drive: int | None = None,
        sort: Literal["taken_desc", "taken_asc", "name", "size_desc"] = "taken_desc",
    ):
        where, params = ["i.missing=0"], []
        if category == "people":
            where.append("i.face_count > 0")
        elif category == "unsorted":
            where.append("i.category IS NULL")
        elif category:
            where.append("i.category=?")
            params.append(category)
        for pid in person:  # every listed person must be in the picture
            where.append("EXISTS (SELECT 1 FROM faces f WHERE f.image_id=i.id AND f.person_id=?)")
            params.append(pid)
        if tag:
            where.append("EXISTS (SELECT 1 FROM tags t WHERE t.image_id=i.id AND t.tag=?)")
            params.append(tag)
        if folder:
            where.append("i.folder=?")
            params.append(folder)
        if q:
            where.append("(i.filename LIKE ? OR EXISTS (SELECT 1 FROM tags t WHERE t.image_id=i.id AND t.tag LIKE ?))")
            params += [f"%{q}%", f"%{q}%"]
        if date_from:
            where.append("i.taken_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("i.taken_at < ?")
            params.append(date_to)
        if drive:
            where.append("i.volume_id=?")
            params.append(drive)
        if duplicates:
            where.append(
                "i.quick_hash IN (SELECT quick_hash FROM images WHERE missing=0 AND quick_hash IS NOT NULL "
                "GROUP BY quick_hash HAVING COUNT(*) > 1)"
            )
        clause = " AND ".join(where)
        total = db.query_one(f"SELECT COUNT(*) AS n FROM images i LEFT JOIN volumes v ON v.id=i.volume_id "
                             f"WHERE {clause}", params)["n"]
        order = "i.quick_hash, i.id" if duplicates else SORTS[sort]
        items = db.query(
            f"SELECT {LIST_COLUMNS} FROM images i LEFT JOIN volumes v ON v.id=i.volume_id "
            f"WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {"total": total, "offset": offset, "limit": limit, "items": items}

    @app.get("/api/images/{image_id}")
    def image_detail(row: dict = Depends(get_image)):
        row.pop("clip_embedding", None)
        dupes = []
        if row["quick_hash"]:
            dupes = db.query(
                "SELECT id, path FROM images WHERE quick_hash=? AND id<>? AND missing=0",
                (row["quick_hash"], row["id"]),
            )
        faces = db.query(
            "SELECT f.id, f.x, f.y, f.w, f.h, f.person_id, p.name AS person_name, f.cluster_id, f.ignored, "
            "f.assigned_by, COALESCE(p.hidden, 0) AS person_hidden "
            "FROM faces f LEFT JOIN persons p ON p.id=f.person_id WHERE f.image_id=? ORDER BY f.x",
            (row["id"],),
        )
        tags_ = [t["tag"] for t in db.query("SELECT tag FROM tags WHERE image_id=? ORDER BY tag", (row["id"],))]
        edits = db.query("SELECT id, path FROM images WHERE edited_from=? AND missing=0", (row["id"],))
        drive = db.query_one("SELECT label, mounted FROM volumes WHERE id=?", (row["volume_id"],)) \
            if row["volume_id"] else None
        row["drive"] = drive["label"] if drive else None
        row["offline"] = int(bool(drive) and not drive["mounted"])
        return {**row, "duplicates": dupes, "faces": faces, "tags": tags_, "edits": edits}

    @app.get("/api/images/{image_id}/thumb")
    def image_thumb(row: dict = Depends(get_image)):
        if not row["thumb"]:
            raise HTTPException(404, "no thumbnail")
        return FileResponse(settings.thumbs_dir / row["thumb"], media_type="image/webp",
                            headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/images/{image_id}/preview")
    def image_preview(row: dict = Depends(get_image)):
        """Original for browser-native formats; HEIC/TIFF are converted to JPEG on the fly."""
        path = existing_file(row)
        if row["ext"] in BROWSER_NATIVE:
            return FileResponse(path, headers={"Cache-Control": "no-cache"})
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg")

    # ---- actions ----------------------------------------------------------------------------------

    @app.post("/api/images/{image_id}/reveal", dependencies=MUTATING)
    def reveal(row: dict = Depends(get_image)):
        platform_ops.reveal_in_folder(existing_file(row))
        return {"ok": True}

    @app.post("/api/images/{image_id}/open", dependencies=MUTATING)
    def open_file(row: dict = Depends(get_image)):
        platform_ops.open_default(existing_file(row))
        return {"ok": True}

    @app.put("/api/images/{image_id}/category", dependencies=MUTATING)
    def set_category(req: CategoryRequest, row: dict = Depends(get_image)):
        if req.category is None:  # unlock and fall back to the model's best guess
            scores = json.loads(row["clip_scores"]) if row["clip_scores"] else None
            best = max(scores, key=scores.get) if scores else None
            db.execute("UPDATE images SET category=?, category_locked=0 WHERE id=?", (best, row["id"]))
        else:
            db.execute("UPDATE images SET category=?, category_locked=1 WHERE id=?", (req.category, row["id"]))
        return {"ok": True}

    @app.post("/api/images/{image_id}/tags", dependencies=MUTATING)
    def add_tag(req: TagRequest, row: dict = Depends(get_image)):
        tag = " ".join(req.tag.split())[:60]
        if not tag:
            raise HTTPException(400, "empty tag")
        db.execute("INSERT OR IGNORE INTO tags(image_id, tag) VALUES (?, ?)", (row["id"], tag))
        return {"ok": True}

    @app.delete("/api/images/{image_id}/tags/{tag}", dependencies=MUTATING)
    def remove_tag(tag: str, row: dict = Depends(get_image)):
        db.execute("DELETE FROM tags WHERE image_id=? AND tag=?", (row["id"], tag))
        return {"ok": True}

    @app.post("/api/images/{image_id}/edit", dependencies=MUTATING)
    def edit_image(req: EditRequest, row: dict = Depends(get_image)):
        src = existing_file(row)
        if req.is_noop:
            raise HTTPException(400, "nothing to change")
        try:
            dest = apply_edit(src, req, settings.backups_dir)
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"could not save the edit: {exc}")
        st = dest.stat()
        db.upsert_images([process_file(str(dest), st.st_size, st.st_mtime, settings.thumbs_dir, settings.thumb_size)])
        new_id = db.query_one("SELECT id FROM images WHERE path=?", (str(dest),))["id"]
        if new_id != row["id"]:  # a copy: link it to its original and carry tags + manual type over
            db.execute("UPDATE images SET edited_from=? WHERE id=?", (row["id"], new_id))
            db.execute("INSERT OR IGNORE INTO tags(image_id, tag) SELECT ?, tag FROM tags WHERE image_id=?",
                       (new_id, row["id"]))
            if row["category_locked"]:
                db.execute("UPDATE images SET category=?, category_locked=1 WHERE id=?", (row["category"], new_id))
        if pipeline.models.status()["ready"]:
            pipeline.analyze_now(new_id)
        return {"id": new_id, "path": str(dest), "copy": new_id != row["id"]}

    # Serve the built UI when present, so a single process runs the whole app.
    dist = _ui_dist()
    if dist:
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")

    return app


def _ui_dist() -> Path | None:
    candidates = [Path(__file__).resolve().parents[2] / "frontend" / "dist"]
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        candidates.insert(0, Path(getattr(sys, "_MEIPASS", "")) / "ui")
    return next((p for p in candidates if p.is_dir()), None)
