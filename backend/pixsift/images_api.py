"""Pictures: browse, detail, thumbnails/previews, and per-picture actions (reveal, type, tags, edit)."""

import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import platform_ops
from .config import Settings
from .db import Database
from .deps import MUTATING, existing_file, get_db, get_image, get_pipeline, get_settings
from .editor import EditRequest, apply_edit
from .media import process_file

router = APIRouter()

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


class CategoryRequest(BaseModel):
    category: Literal["document", "screenshot", "photo", "graphic"] | None  # None = back to automatic


class TagRequest(BaseModel):
    tag: str



@router.get("/folders")
def folders(db: Database = Depends(get_db)):
    return db.query(
        "SELECT folder, COUNT(*) AS count FROM images WHERE missing=0 GROUP BY folder ORDER BY folder"
    )

@router.get("/tags")
def tags(db: Database = Depends(get_db)):
    return db.query(
        "SELECT t.tag, COUNT(*) AS count FROM tags t JOIN images i ON i.id=t.image_id "
        "WHERE i.missing=0 GROUP BY t.tag ORDER BY t.tag COLLATE NOCASE"
    )

@router.get("/images")
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
    db: Database = Depends(get_db),
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
        # IN, not a correlated EXISTS: SQLite looks the person's photos up once via ix_faces_person_image
        # instead of scanning their faces again for every picture in the library.
        where.append("i.id IN (SELECT image_id FROM faces WHERE person_id=?)")
        params.append(pid)
    if tag:
        where.append("i.id IN (SELECT image_id FROM tags WHERE tag=?)")
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

@router.get("/images/{image_id}")
def image_detail(row: dict = Depends(get_image), db: Database = Depends(get_db)):
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

@router.get("/images/{image_id}/thumb")
def image_thumb(row: dict = Depends(get_image), settings: Settings = Depends(get_settings)):
    if not row["thumb"]:
        raise HTTPException(404, "no thumbnail")
    return FileResponse(settings.thumbs_dir / row["thumb"], media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})

@router.get("/images/{image_id}/preview")
def image_preview(row: dict = Depends(get_image), db: Database = Depends(get_db)):
    """Original for browser-native formats; HEIC/TIFF are converted to JPEG on the fly."""
    path = existing_file(db, row)
    if row["ext"] in BROWSER_NATIVE:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=88)
    return Response(buf.getvalue(), media_type="image/jpeg")

# ---- actions ----------------------------------------------------------------------------------

@router.post("/images/{image_id}/reveal", dependencies=MUTATING)
def reveal(row: dict = Depends(get_image), db: Database = Depends(get_db)):
    platform_ops.reveal_in_folder(existing_file(db, row))
    return {"ok": True}

@router.post("/images/{image_id}/open", dependencies=MUTATING)
def open_file(row: dict = Depends(get_image), db: Database = Depends(get_db)):
    platform_ops.open_default(existing_file(db, row))
    return {"ok": True}

@router.put("/images/{image_id}/category", dependencies=MUTATING)
def set_category(req: CategoryRequest, row: dict = Depends(get_image), db: Database = Depends(get_db)):
    if req.category is None:  # unlock and fall back to the model's best guess
        scores = json.loads(row["clip_scores"]) if row["clip_scores"] else None
        best = max(scores, key=scores.get) if scores else None
        db.execute("UPDATE images SET category=?, category_locked=0 WHERE id=?", (best, row["id"]))
    else:
        db.execute("UPDATE images SET category=?, category_locked=1 WHERE id=?", (req.category, row["id"]))
    return {"ok": True}

@router.post("/images/{image_id}/tags", dependencies=MUTATING)
def add_tag(req: TagRequest, row: dict = Depends(get_image), db: Database = Depends(get_db)):
    tag = " ".join(req.tag.split())[:60]
    if not tag:
        raise HTTPException(400, "empty tag")
    db.execute("INSERT OR IGNORE INTO tags(image_id, tag) VALUES (?, ?)", (row["id"], tag))
    return {"ok": True}

@router.delete("/images/{image_id}/tags/{tag}", dependencies=MUTATING)
def remove_tag(tag: str, row: dict = Depends(get_image), db: Database = Depends(get_db)):
    db.execute("DELETE FROM tags WHERE image_id=? AND tag=?", (row["id"], tag))
    return {"ok": True}

@router.post("/images/{image_id}/edit", dependencies=MUTATING)
def edit_image(req: EditRequest, row: dict = Depends(get_image), db: Database = Depends(get_db),
               settings: Settings = Depends(get_settings), pipeline=Depends(get_pipeline)):
    src = existing_file(db, row)
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
