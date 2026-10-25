"""External drives (offline pictures, remounts, auto re-scan) and hidden people."""

import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pixsift import faces as F
from pixsift.api import create_app
from pixsift.config import Settings
from pixsift.volumes import Mount

UI = {"X-PixSift": "1"}


def jpeg(path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), color).save(path, quality=90)


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", min_file_bytes=100, token="t"))
    mounts: list[Mount] = []
    app.state.watcher.lister = lambda: list(mounts)
    # These tests are about scanning: skip the model download / analysis step of each job.
    app.state.pipeline.models.ensure = lambda cancel=None: None
    app.state.pipeline._analyze_pending = lambda *args: None
    with TestClient(app, cookies={"pixsift_token": "t"}) as c:
        yield c, app, mounts, tmp_path


def scan(c, app, roots):
    c.post("/api/scan", json={"roots": roots, "analyze": False}, headers=UI).raise_for_status()
    app.state.pipeline.join(30)


def test_drive_pictures_stay_while_unplugged_and_come_back_at_a_new_mount(env):
    c, app, mounts, tmp = env
    drive = tmp / "Volumes" / "Photos"
    jpeg(drive / "trip" / "a.jpg")
    jpeg(drive / "trip" / "b.jpg", "blue")
    mounts.append(Mount("mac:UUID-1", "Photos", str(drive)))
    app.state.watcher.sync()
    assert [d["status"] for d in c.get("/api/drives").json()] == ["new"]
    assert c.get("/api/job").json()["new_drives"][0]["label"] == "Photos"

    drive_id = c.get("/api/drives").json()[0]["id"]
    c.post(f"/api/drives/{drive_id}/scan", headers=UI).raise_for_status()
    app.state.pipeline.join(30)
    d = c.get("/api/drives").json()[0]
    assert (d["status"], d["pictures"]) == ("tracked", 2)

    # Unplug: the drive's folder disappears from disk.
    moved = tmp / "Volumes" / "Photos 1"
    shutil.move(drive, moved)
    mounts.clear()
    app.state.watcher.sync()
    items = c.get("/api/images").json()["items"]
    assert len(items) == 2 and all(i["offline"] == 1 and i["drive"] == "Photos" for i in items)
    r = c.get(f"/api/images/{items[0]['id']}/preview")
    assert r.status_code == 409 and "Photos" in r.json()["detail"]

    # A re-scan while unplugged must not mark them as deleted.
    app.state.pipeline.start([str(drive)], analyze=False)
    app.state.pipeline.join(30)
    assert c.get("/api/images").json()["total"] == 2

    # Plug in again, mounted elsewhere ("Photos 1"): paths are remapped and the drive re-scanned automatically.
    jpeg(moved / "trip" / "new.jpg", "green")
    mounts.append(Mount("mac:UUID-1", "Photos", str(moved)))
    app.state.watcher.sync()
    app.state.pipeline.join(30)
    items = c.get("/api/images", params={"drive": drive_id}).json()["items"]
    assert sorted(i["filename"] for i in items) == ["a.jpg", "b.jpg", "new.jpg"]
    assert all(i["path"].startswith(str(moved)) and i["offline"] == 0 for i in items)
    assert c.get(f"/api/images/{items[0]['id']}/preview").status_code == 200


def test_ignored_and_untracked_drives_are_never_scanned(env):
    c, app, mounts, tmp = env
    started = []
    app.state.watcher.start_scan = lambda roots: started.append(roots) or True
    mounts.append(Mount("win:ABCD1234", "Backup", str(tmp)))
    app.state.watcher.sync()
    drive_id = c.get("/api/drives").json()[0]["id"]
    c.post(f"/api/drives/{drive_id}/ignore", headers=UI).raise_for_status()
    mounts.clear()
    app.state.watcher.sync()
    mounts.append(Mount("win:ABCD1234", "Backup", str(tmp)))
    app.state.watcher.sync()
    assert started == [] and c.get("/api/job").json()["new_drives"] == []


# ---- hidden people --------------------------------------------------------------------------------

def vec(axis, extra=None):
    v = np.zeros(128, np.float32)
    v[axis] = 1
    if extra is not None:
        v[extra] = 0.15
    return v / np.linalg.norm(v)


def add_face(db, n, emb, year=2020):
    img = db.execute(
        "INSERT INTO images(path, folder, filename, ext, size, mtime, taken_at, thumb, analyzed_at) "
        "VALUES (?, '/x', ?, '.jpg', 1, 0, ?, 't', 'now')", (f"/x/{n}.jpg", f"{n}.jpg", f"{year}-01-01T00:00:00")
    ).lastrowid
    return db.execute("INSERT INTO faces(image_id, x, y, w, h, score, embedding) VALUES (?, 0, 0, .2, .2, .9, ?)",
                      (img, F.to_blob(emb))).lastrowid


def test_hidden_person_is_suppressed_then_can_be_named_later(env):
    c, app, _, _ = env
    db = app.state.db
    db.set_setting("ask_min_photos", "2")
    stranger = [add_face(db, i, vec(0, 10 + i)) for i in range(3)]
    friend = [add_face(db, 10 + i, vec(1, 20 + i)) for i in range(2)]
    F.recluster(db)
    groups = c.get("/api/face-groups").json()
    group = next(g for g in groups if {f["id"] for f in g["faces"]} == set(stranger))

    c.post(f"/api/face-groups/{group['cluster_id']}/hide", headers=UI).raise_for_status()
    assert len(c.get("/api/face-groups").json()) == 1  # only the friend is still asked about
    assert c.get("/api/persons").json() == []           # hidden people aren't listed as people
    hidden = c.get("/api/persons", params={"hidden": True}).json()
    assert len(hidden) == 1 and hidden[0]["count"] == 3

    # A new photo of the stranger is filed under the hidden person quietly; not shown for review.
    later = add_face(db, 50, vec(0, 40))
    F.auto_assign(db)
    assert db.query_one("SELECT person_id FROM faces WHERE id=?", (later,))["person_id"] == hidden[0]["id"]
    assert c.get("/api/stats").json()["auto_named"] == 0

    # Later: name them. Every photo collected meanwhile comes along.
    r = c.post(f"/api/persons/{hidden[0]['id']}/unhide", json={"name": "Neighbour"}, headers=UI).json()
    person = next(p for p in c.get("/api/persons").json() if p["id"] == r["person_id"])
    assert (person["name"], person["count"], person["auto_count"]) == ("Neighbour", 4, 1)
    assert c.get("/api/persons", params={"hidden": True}).json() == []
    assert friend  # untouched


def test_unhiding_into_an_existing_name_merges(env):
    c, app, _, _ = env
    db = app.state.db
    ids = [add_face(db, i, vec(0, 10 + i)) for i in range(2)]
    anna = F.get_or_create_person(db, "Anna")
    hidden = F.hide_faces(db, ids)
    r = c.post(f"/api/persons/{hidden}/unhide", json={"name": "anna"}, headers=UI).json()
    assert r["person_id"] == anna
    assert [(p["name"], p["count"]) for p in c.get("/api/persons").json()] == [("Anna", 2)]


def test_ask_again_returns_faces_to_the_questions(env):
    c, app, _, _ = env
    db = app.state.db
    db.set_setting("ask_min_photos", "2")
    ids = [add_face(db, i, vec(0, 10 + i)) for i in range(2)]
    [add_face(db, 10 + i, vec(1, 20 + i)) for i in range(2)]  # someone else, still unnamed
    hidden = F.hide_faces(db, ids)
    c.post(f"/api/persons/{hidden}/unhide", json={}, headers=UI).raise_for_status()
    app.state.pipeline.join(30)  # regrouping runs as a background job
    groups = c.get("/api/face-groups").json()
    assert c.get("/api/persons", params={"hidden": True}).json() == []
    assert any({f["id"] for f in g["faces"]} == set(ids) for g in groups)


def test_ask_threshold_setting(env):
    c, app, _, _ = env
    db = app.state.db
    [add_face(db, i, vec(0, 10 + i)) for i in range(2)]
    [add_face(db, 10 + i, vec(1, 20 + i)) for i in range(4)]
    F.recluster(db)
    assert [g["count"] for g in c.get("/api/face-groups").json()] == [4]  # default: 3+ photos
    c.put("/api/settings", json={"ask_min_photos": 2}, headers=UI).raise_for_status()
    assert len(c.get("/api/face-groups").json()) == 2
    c.put("/api/settings", json={"ask_min_photos": 3}, headers=UI).raise_for_status()
    assert [g["count"] for g in c.get("/api/face-groups").json()] == [4]
    assert c.put("/api/settings", json={"ask_min_photos": 1}, headers=UI).status_code == 422
