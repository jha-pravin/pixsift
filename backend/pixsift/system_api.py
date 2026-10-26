"""App, jobs, scan sources, drives and settings."""

import os
import string
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import __version__, platform_ops
from .config import Settings
from .db import Database
from .deps import MUTATING, get_db, get_pipeline, get_settings, get_watcher
from .faces import ask_min_photos

router = APIRouter()


class ScanRequest(BaseModel):
    roots: list[str]
    analyze: bool = True


class DriveUpdate(BaseModel):
    auto_scan: bool


class SettingsUpdate(BaseModel):
    ask_min_photos: int = Field(ge=2, le=100)


@router.get("/health")
def health():
    return {"version": __version__, "platform": sys.platform, "reveal_label": platform_ops.reveal_label()}

@router.get("/stats")
def stats(db: Database = Depends(get_db)):
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

@router.get("/dashboard")
def dashboard(db: Database = Depends(get_db)):
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
    return {"categories": cats, "recent": [r["id"] for r in recent], "stats": stats(db)}

@router.get("/roots")
def roots(db: Database = Depends(get_db)):
    return db.query("SELECT path, last_scanned FROM scan_roots ORDER BY path")

@router.get("/suggested-roots")
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

@router.post("/scan", dependencies=MUTATING)
def start_scan(req: ScanRequest, settings: Settings = Depends(get_settings),
               pipeline=Depends(get_pipeline), watcher=Depends(get_watcher)):
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

@router.get("/drives")
def drives(db: Database = Depends(get_db)):
    return db.query(
        "SELECT v.id, v.label, v.mount, v.mounted, v.status, v.auto_scan, v.last_seen, v.last_scanned, "
        "(SELECT COUNT(*) FROM images i WHERE i.volume_id=v.id AND i.missing=0) AS pictures "
        "FROM volumes v WHERE v.status<>'ignored' OR v.mounted=1 ORDER BY v.mounted DESC, v.label"
    )

def get_drive(drive_id: int, db: Database = Depends(get_db)) -> dict:
    row = db.query_one("SELECT * FROM volumes WHERE id=?", (drive_id,))
    if not row:
        raise HTTPException(404, "drive not found")
    return row

@router.post("/drives/{drive_id}/scan", dependencies=MUTATING)
def scan_drive(drive: dict = Depends(get_drive), pipeline=Depends(get_pipeline), watcher=Depends(get_watcher)):
    if not drive["mounted"]:
        raise HTTPException(409, f"Connect the drive “{drive['label']}” first")
    if not pipeline.start(watcher.track(drive["id"])):
        raise HTTPException(409, "a job is already running")
    return pipeline.snapshot()

@router.post("/drives/{drive_id}/ignore", dependencies=MUTATING)
def ignore_drive(drive: dict = Depends(get_drive), db: Database = Depends(get_db)):
    db.execute("UPDATE volumes SET status='ignored' WHERE id=?", (drive["id"],))
    return {"ok": True}

@router.patch("/drives/{drive_id}", dependencies=MUTATING)
def update_drive(req: DriveUpdate, drive: dict = Depends(get_drive), db: Database = Depends(get_db)):
    db.execute("UPDATE volumes SET auto_scan=? WHERE id=?", (int(req.auto_scan), drive["id"]))
    return {"ok": True}

# ---- settings ---------------------------------------------------------------------------------

@router.get("/settings")
def read_settings(db: Database = Depends(get_db)):
    return {"ask_min_photos": ask_min_photos(db)}

@router.put("/settings", dependencies=MUTATING)
def put_settings(req: SettingsUpdate, db: Database = Depends(get_db)):
    db.set_setting("ask_min_photos", str(req.ask_min_photos))
    return read_settings(db)

@router.post("/analyze", dependencies=MUTATING)
def start_analyze(pipeline=Depends(get_pipeline)):
    if not pipeline.start(None):
        raise HTTPException(409, "a job is already running")
    return pipeline.snapshot()

@router.get("/job")
def job_status(pipeline=Depends(get_pipeline)):
    return pipeline.snapshot()

@router.post("/job/cancel", dependencies=MUTATING)
def cancel_job(pipeline=Depends(get_pipeline)):
    pipeline.cancel()
    return pipeline.snapshot()
