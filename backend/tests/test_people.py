"""End-to-end: scan -> analyse -> group faces -> name -> timeline -> edit carries names over.

Needs the ML models. Set PIXSIFT_MODELS_DIR to a folder that has them (the app downloads them on first run);
by default the repo's demo data folder is used, and the tests are skipped when the models aren't there.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageEnhance, ImageOps

from pixsift.api import create_app
from pixsift.config import Settings
from pixsift.models import ModelStore

FIX = Path(__file__).parent / "fixtures"
MODELS = Path(os.environ.get("PIXSIFT_MODELS_DIR") or Path(__file__).parents[2] / ".demo-data" / "models")
UI = {"X-PixSift": "1"}

pytestmark = pytest.mark.skipif(not ModelStore(MODELS).status()["ready"], reason="ML models not downloaded")


def save(img, path, date):
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = date
    exif[0x010F], exif[0x0110] = "Apple", "iPhone 15"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", exif=exif, quality=90)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXSIFT_MODELS_DIR", str(MODELS))
    lib = tmp_path / "lib"
    a = Image.open(FIX / "astronaut.jpg")
    for i, v in enumerate([a, ImageOps.mirror(a), ImageEnhance.Brightness(a).enhance(0.8)]):
        save(v, lib / f"astro_{i}.jpg", f"20{20 + i}:06:01 10:00:00")
    c = Image.open(FIX / "cameraman.jpg")
    for i, v in enumerate([c, ImageOps.mirror(c)]):
        save(v, lib / f"cam_{i}.jpg", f"2019:0{i + 1}:01 10:00:00")
    Image.open(FIX / "page.jpg").save(lib / "page.jpg")
    app = create_app(Settings(data_dir=tmp_path / "data", min_file_bytes=1000, token="test-token"))
    app.state.db.set_setting("ask_min_photos", "2")  # the test library is tiny: ask about 2-photo groups too
    with TestClient(app, cookies={"pixsift_token": "test-token"}) as tc:
        tc.post("/api/scan", json={"roots": [str(lib)]}, headers=UI).raise_for_status()
        app.state.pipeline.join(120)
        tc.lib = lib
        yield tc


def ids_by_name(client, **params):
    return {i["filename"]: i["id"] for i in client.get("/api/images", params=params).json()["items"]}


def test_categories_and_dashboard(client):
    job = client.get("/api/job").json()
    assert job["state"] == "done" and job["analyzed"] == 6
    assert set(ids_by_name(client, category="people")) == {"astro_0.jpg", "astro_1.jpg", "astro_2.jpg",
                                                           "cam_0.jpg", "cam_1.jpg"}
    assert set(ids_by_name(client, category="document")) == {"page.jpg"}
    cats = {c["key"]: c["count"] for c in client.get("/api/dashboard").json()["categories"]}
    assert cats["people"] == 5 and cats["document"] == 1


def test_groups_name_timeline_and_suggestion(client):
    groups = client.get("/api/face-groups").json()
    assert sorted(g["count"] for g in groups) == [2, 3]
    astro = next(g for g in groups if g["count"] == 3)
    r = client.post(f"/api/face-groups/{astro['cluster_id']}/name", json={"name": "Eileen"}, headers=UI)
    person_id = r.json()["person_id"]

    people = client.get("/api/persons").json()
    assert [(p["name"], p["count"]) for p in people] == [("Eileen", 3)]
    timeline = client.get("/api/images", params={"person": person_id, "sort": "taken_asc"}).json()["items"]
    assert [i["filename"] for i in timeline] == ["astro_0.jpg", "astro_1.jpg", "astro_2.jpg"]
    detail = client.get(f"/api/persons/{person_id}").json()
    assert detail["first_seen"].startswith("2020") and detail["years"][0]["year"] == "2020"

    # The other group gets no suggestion (different person); naming a single face works too.
    cam = next(g for g in client.get("/api/face-groups").json())
    assert cam["suggestion"] is None
    face_id = cam["faces"][0]["id"]
    r = client.post("/api/faces/assign", json={"face_ids": [face_id], "name": "Cam"}, headers=UI).json()
    # Naming one photo finds the other one right away, marked for review.
    assert r["auto_named"] == 1
    cam_person = next(p for p in client.get("/api/persons").json() if p["name"] == "Cam")
    assert (cam_person["count"], cam_person["auto_count"]) == (2, 1)
    other = cam["faces"][1]["id"]
    detail = client.get(f"/api/images/{client.get(f'/api/persons/{cam_person['id']}/faces').json()[0]['image_id']}").json()
    assert [(f["person_name"], f["assigned_by"]) for f in detail["faces"]] == [("Cam", "auto")]
    client.post(f"/api/persons/{cam_person['id']}/confirm-auto", json={}, headers=UI).raise_for_status()
    assert next(p for p in client.get("/api/persons").json() if p["name"] == "Cam")["auto_count"] == 0
    assert client.get(f"/api/faces/{other}/suggestion").json()["suggestion"]["name"] == "Cam"


def test_edit_copy_keeps_names_and_reject(client):
    groups = client.get("/api/face-groups").json()
    astro = next(g for g in groups if g["count"] == 3)
    pid = client.post(f"/api/face-groups/{astro['cluster_id']}/name", json={"name": "Eileen"}, headers=UI).json()[
        "person_id"]
    src = ids_by_name(client)["astro_0.jpg"]
    r = client.post(f"/api/images/{src}/edit", json={"flip_h": True, "brightness": 1.1}, headers=UI).json()
    assert r["copy"] and Path(r["path"]).name == "astro_0_edited.jpg"
    edited = client.get(f"/api/images/{r['id']}").json()
    assert edited["edited_from"] == src and [f["person_name"] for f in edited["faces"]] == ["Eileen"]
    assert client.get(f"/api/persons/{pid}").json()["count"] == 4

    face = edited["faces"][0]["id"]
    client.post(f"/api/faces/{face}/reject", headers=UI).raise_for_status()
    assert client.get(f"/api/faces/{face}/suggestion").json()["suggestion"] is None


def test_manual_category_survives_reanalysis(client):
    img = ids_by_name(client)["page.jpg"]
    client.put(f"/api/images/{img}/category", json={"category": "graphic"}, headers=UI).raise_for_status()
    client.app.state.pipeline.analyze_now(img)
    assert client.get(f"/api/images/{img}").json()["category"] == "graphic"
    client.put(f"/api/images/{img}/category", json={"category": None}, headers=UI).raise_for_status()
    assert client.get(f"/api/images/{img}").json()["category"] == "document"


def test_tags(client):
    img = ids_by_name(client)["cam_0.jpg"]
    client.post(f"/api/images/{img}/tags", json={"tag": " Old  photos "}, headers=UI).raise_for_status()
    assert client.get("/api/tags").json() == [{"tag": "Old photos", "count": 1}]
    assert set(ids_by_name(client, q="old")) == {"cam_0.jpg"}
    client.delete(f"/api/images/{img}/tags/Old photos", headers=UI).raise_for_status()
    assert client.get("/api/tags").json() == []
