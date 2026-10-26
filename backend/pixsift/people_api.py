"""People & faces endpoints: name groups, tag single faces, person timeline summary."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from . import faces as face_ops
from .db import Database
from .deps import MUTATING, get_db


router = APIRouter()


class NameTarget(BaseModel):
    """Exactly one of: an existing person, a (new or existing) name, or clear=True to unname."""
    person_id: int | None = None
    name: str | None = None
    clear: bool = False

    @model_validator(mode="after")
    def _one(self):
        if sum([self.person_id is not None, bool(self.name and self.name.strip()), self.clear]) != 1:
            raise ValueError("give exactly one of person_id, name or clear")
        return self

    def resolve(self, db: Database) -> int | None:
        if self.clear:
            return None
        if self.person_id is not None:
            if not db.query_one("SELECT 1 FROM persons WHERE id=?", (self.person_id,)):
                raise HTTPException(404, "person not found")
            return self.person_id
        return face_ops.get_or_create_person(db, self.name)


class AssignRequest(NameTarget):
    face_ids: list[int] = Field(min_length=1, max_length=5000)


class PersonUpdate(BaseModel):
    name: str | None = None
    cover_face_id: int | None = None


class MergeRequest(BaseModel):
    into_id: int


class UnhideRequest(BaseModel):
    name: str | None = None  # None/empty = put their faces back into "Who are these people?"


class ConfirmRequest(BaseModel):
    face_ids: list[int] | None = Field(None, max_length=5000)  # None = all automatic matches of this person


# ---- faces --------------------------------------------------------------------------------------

@router.get("/faces/{face_id}/crop")
def face_crop(face_id: int, request: Request, db: Database = Depends(get_db)):
    row = db.query_one("SELECT crop FROM faces WHERE id=?", (face_id,))
    if not row or not row["crop"]:
        raise HTTPException(404, "face not found")
    return FileResponse(request.app.state.settings.thumbs_dir / row["crop"], media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/faces/{face_id}/suggestion")
def face_suggestion(face_id: int, db: Database = Depends(get_db)):
    return {"suggestion": face_ops.suggest_for_face(db, face_id)}


@router.post("/faces/assign", dependencies=MUTATING)
def assign(req: AssignRequest, db: Database = Depends(get_db)):
    person_id = req.resolve(db)
    face_ops.assign_faces(db, req.face_ids, person_id)
    auto = face_ops.auto_assign(db, person_id) if person_id else 0  # find this person's other photos right away
    return {"person_id": person_id, "auto_named": auto}


@router.post("/faces/{face_id}/reject", dependencies=MUTATING)
def reject(face_id: int, db: Database = Depends(get_db)):
    face_ops.reject_face(db, face_id)
    return {"ok": True}


@router.post("/faces/{face_id}/hide", dependencies=MUTATING)
def hide_face(face_id: int, db: Database = Depends(get_db)):
    person_id = face_ops.hide_faces(db, [face_id])
    face_ops.auto_assign(db, person_id)
    return {"person_id": person_id}


@router.post("/faces/{face_id}/ignore", dependencies=MUTATING)
def ignore(face_id: int, db: Database = Depends(get_db)):
    db.execute("UPDATE faces SET ignored=1, person_id=NULL, cluster_id=NULL WHERE id=?", (face_id,))
    return {"ok": True}


# ---- unnamed groups -----------------------------------------------------------------------------

@router.get("/face-groups")
def face_groups(db: Database = Depends(get_db)):
    return face_ops.unnamed_groups(db)


def _group_face_ids(db: Database, cluster_id: int) -> list[int]:
    ids = [r["id"] for r in db.query(
        "SELECT id FROM faces WHERE cluster_id=? AND person_id IS NULL AND ignored=0", (cluster_id,))]
    if not ids:
        raise HTTPException(404, "group not found (faces may have been regrouped; refresh)")
    return ids


@router.post("/face-groups/{cluster_id}/name", dependencies=MUTATING)
def name_group(cluster_id: int, req: NameTarget, db: Database = Depends(get_db)):
    if req.clear:
        raise HTTPException(400, "use ignore to dismiss a group")
    person_id = req.resolve(db)
    face_ops.assign_faces(db, _group_face_ids(db, cluster_id), person_id)
    return {"person_id": person_id, "auto_named": face_ops.auto_assign(db, person_id)}


@router.post("/face-groups/{cluster_id}/hide", dependencies=MUTATING)
def hide_group(cluster_id: int, db: Database = Depends(get_db)):
    person_id = face_ops.hide_faces(db, _group_face_ids(db, cluster_id))
    face_ops.auto_assign(db, person_id)  # quietly collect this person's other photos too
    return {"person_id": person_id}


@router.post("/face-groups/{cluster_id}/ignore", dependencies=MUTATING)
def ignore_group(cluster_id: int, db: Database = Depends(get_db)):
    ids = _group_face_ids(db, cluster_id)
    db.execute(f"UPDATE faces SET ignored=1, cluster_id=NULL WHERE id IN ({','.join('?' * len(ids))})", ids)
    return {"ok": True}


# ---- persons ------------------------------------------------------------------------------------

_PERSON_SQL = """
SELECT p.id, p.name, p.hidden,
       COALESCE(p.cover_face_id, (SELECT f2.id FROM faces f2 WHERE f2.person_id=p.id ORDER BY f2.score DESC LIMIT 1))
           AS cover_face_id,
       COUNT(DISTINCT f.image_id) AS count,
       COUNT(DISTINCT CASE WHEN f.assigned_by='auto' THEN f.id END) AS auto_count,
       MIN(i.taken_at) AS first_seen, MAX(i.taken_at) AS last_seen
FROM persons p
LEFT JOIN faces f ON f.person_id = p.id
LEFT JOIN images i ON i.id = f.image_id AND i.missing = 0
"""


@router.get("/persons")
def list_persons(db: Database = Depends(get_db), sort: str = Query("count"), hidden: bool = False):
    order = "p.name COLLATE NOCASE" if sort == "name" else "count DESC, p.name COLLATE NOCASE"
    return db.query(f"{_PERSON_SQL} WHERE p.hidden=? GROUP BY p.id ORDER BY {order}", (int(hidden),))


@router.get("/persons/{person_id}")
def person_detail(person_id: int, db: Database = Depends(get_db)):
    person = db.query_one(f"{_PERSON_SQL} WHERE p.id=? GROUP BY p.id", (person_id,))
    if not person:
        raise HTTPException(404, "person not found")
    imgs = "SELECT DISTINCT image_id FROM faces WHERE person_id=?"
    cameras = db.query(
        f"SELECT TRIM(COALESCE(camera_make,'') || ' ' || COALESCE(camera_model,'')) AS camera, COUNT(*) AS count "
        f"FROM images WHERE id IN ({imgs}) AND missing=0 AND camera_model IS NOT NULL "
        f"GROUP BY camera ORDER BY count DESC LIMIT 5", (person_id,))
    folders = db.query(
        f"SELECT folder, COUNT(*) AS count FROM images WHERE id IN ({imgs}) AND missing=0 "
        f"GROUP BY folder ORDER BY count DESC LIMIT 5", (person_id,))
    years = db.query(
        f"SELECT substr(taken_at, 1, 4) AS year, COUNT(*) AS count FROM images WHERE id IN ({imgs}) AND missing=0 "
        f"GROUP BY year ORDER BY year", (person_id,))
    places = db.query(
        f"SELECT id, gps_lat AS lat, gps_lon AS lon, taken_at FROM images WHERE id IN ({imgs}) AND missing=0 "
        f"AND gps_lat IS NOT NULL ORDER BY taken_at DESC LIMIT 200", (person_id,))
    together = db.query(
        "SELECT p.id, p.name, p.hidden, COUNT(DISTINCT f2.image_id) AS count FROM faces f1 "
        "JOIN faces f2 ON f2.image_id=f1.image_id AND f2.person_id IS NOT NULL AND f2.person_id<>f1.person_id "
        "JOIN persons p ON p.id=f2.person_id AND p.hidden=0 WHERE f1.person_id=? GROUP BY p.id ORDER BY count DESC LIMIT 8",
        (person_id,))
    return {**person, "cameras": cameras, "folders": folders, "years": years, "places": places, "together": together}


@router.get("/persons/{person_id}/faces")
def person_faces(person_id: int, db: Database = Depends(get_db),
                 offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    return db.query(
        "SELECT f.id, f.image_id, f.assigned_by FROM faces f JOIN images i ON i.id=f.image_id "
        "WHERE f.person_id=? AND i.missing=0 ORDER BY f.assigned_by='auto' DESC, i.taken_at DESC LIMIT ? OFFSET ?",
        (person_id, limit, offset))


@router.post("/persons/{person_id}/confirm-auto", dependencies=MUTATING)
def confirm_auto(person_id: int, req: ConfirmRequest, db: Database = Depends(get_db)):
    face_ops.confirm_auto(db, person_id, req.face_ids)
    return {"auto_named": face_ops.auto_assign(db, person_id)}  # more confirmed faces can recognise more photos


@router.post("/persons/{person_id}/unhide", dependencies=MUTATING)
def unhide(person_id: int, req: UnhideRequest, request: Request, db: Database = Depends(get_db)):
    if not db.query_one("SELECT 1 FROM persons WHERE id=? AND hidden=1", (person_id,)):
        raise HTTPException(404, "hidden person not found")
    new_id = face_ops.unhide_person(db, person_id, req.name)
    if new_id is None:
        _regroup(request)
    return {"person_id": new_id}


def _regroup(request: Request) -> None:
    """Regroup unnamed faces in the background job (takes ~30 s per 20k faces). If a job is already running,
    the next one regroups them."""
    request.app.state.pipeline.start(None)


@router.post("/persons", dependencies=MUTATING)
def create_person(req: PersonUpdate, db: Database = Depends(get_db)):
    if not req.name or not req.name.strip():
        raise HTTPException(400, "name is required")
    return {"id": face_ops.get_or_create_person(db, req.name)}


@router.patch("/persons/{person_id}", dependencies=MUTATING)
def update_person(person_id: int, req: PersonUpdate, db: Database = Depends(get_db)):
    if req.name is not None:
        name = " ".join(req.name.split())
        clash = db.query_one("SELECT id FROM persons WHERE name=? AND id<>?", (name, person_id))
        if clash:
            raise HTTPException(409, f"'{name}' already exists — merge instead")
        if not name:
            raise HTTPException(400, "name is required")
        db.execute("UPDATE persons SET name=? WHERE id=?", (name, person_id))
    if req.cover_face_id is not None:
        db.execute("UPDATE persons SET cover_face_id=? WHERE id=?", (req.cover_face_id, person_id))
    return {"ok": True}


@router.delete("/persons/{person_id}", dependencies=MUTATING)
def delete_person(person_id: int, request: Request, db: Database = Depends(get_db)):
    """Forget the name; faces go back to unnamed groups (pictures are untouched)."""
    db.execute("UPDATE faces SET person_id=NULL, assigned_by=NULL WHERE person_id=?", (person_id,))
    db.execute("DELETE FROM persons WHERE id=?", (person_id,))
    _regroup(request)
    return {"ok": True}


@router.post("/persons/{person_id}/merge", dependencies=MUTATING)
def merge(person_id: int, req: MergeRequest, db: Database = Depends(get_db)):
    if person_id == req.into_id:
        raise HTTPException(400, "cannot merge a person into themselves")
    face_ops.merge_persons(db, person_id, req.into_id)
    return {"ok": True}
