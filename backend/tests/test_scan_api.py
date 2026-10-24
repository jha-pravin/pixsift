import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pixsift.api import create_app
from pixsift.config import Settings

UI = {"X-PixSift": "1"}


def make_jpeg(path, size=(800, 600), exif_date=None, orientation=None, color="red"):
    img = Image.new("RGB", size, color)
    exif = Image.Exif()
    if exif_date:
        exif.get_ifd(0x8769)[0x9003] = exif_date  # Exif IFD -> DateTimeOriginal
        exif[0x010F] = "TestCam"
        exif[0x0110] = "Model X"
    if orientation:
        exif[0x0112] = orientation
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", exif=exif, quality=95)
    return path


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "photos"
    make_jpeg(root / "a.jpg", exif_date="2021:06:15 10:30:00")
    make_jpeg(root / "sub" / "b.jpg", size=(600, 400), orientation=6, color="blue")
    make_jpeg(root / "sub" / "b_copy.jpg", size=(600, 400), orientation=6, color="blue")  # duplicate
    Image.new("RGB", (900, 500), "green").save(root / "shot.png")
    (root / "notes.txt").write_text("not an image")
    make_jpeg(root / ".hidden" / "h.jpg")
    make_jpeg(root / "Lib.photoslibrary" / "x.jpg")
    (root / "broken.jpg").write_bytes(b"\xff\xd8" + b"0" * 20000)
    return root


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", min_file_bytes=1000, token="test-token")
    app = create_app(settings)
    with TestClient(app, cookies={"pixsift_token": "test-token"}) as c:
        c.pipeline = app.state.pipeline
        yield c


def scan(client, root):
    r = client.post("/api/scan", json={"roots": [str(root)], "analyze": False}, headers=UI)
    assert r.status_code == 200, r.text
    client.pipeline.join(30)
    return client.get("/api/job").json()


def test_scan_indexes_images_and_skips_noise(client, lib):
    status = scan(client, lib)
    assert status["state"] == "done"
    names = {i["filename"] for i in client.get("/api/images", params={"limit": 50}).json()["items"]}
    assert names == {"a.jpg", "b.jpg", "b_copy.jpg", "shot.png", "broken.jpg"}
    assert status["errors"] == 1


def test_metadata_extraction(client, lib):
    scan(client, lib)
    items = {i["filename"]: i for i in client.get("/api/images").json()["items"]}
    a = client.get(f"/api/images/{items['a.jpg']['id']}").json()
    assert a["taken_at"] == "2021-06-15T10:30:00" and a["date_source"] == "exif"
    assert a["camera_make"] == "TestCam" and a["camera_model"] == "Model X"
    b = items["b.jpg"]
    assert (b["width"], b["height"]) == (400, 600)  # rotated by EXIF orientation
    assert items["shot.png"]["date_source"] == "file"


def test_duplicates_and_stats(client, lib):
    scan(client, lib)
    stats = client.get("/api/stats").json()
    assert stats["total"] == 5 and stats["duplicate_groups"] == 1 and stats["duplicate_files"] == 1
    b = next(i for i in client.get("/api/images").json()["items"] if i["filename"] == "b.jpg")
    assert [d["path"] for d in client.get(f"/api/images/{b['id']}").json()["duplicates"]] == [
        str(lib / "sub" / "b_copy.jpg")
    ]


def test_rescan_is_incremental_and_tracks_deletions(client, lib):
    scan(client, lib)
    os.remove(lib / "shot.png")
    status = scan(client, lib)
    assert status["processed"] == 0 and status["unchanged"] == 4 and status["missing"] == 1
    assert client.get("/api/images").json()["total"] == 4


def test_thumb_and_preview(client, lib):
    scan(client, lib)
    a = next(i for i in client.get("/api/images").json()["items"] if i["filename"] == "a.jpg")
    t = client.get(f"/api/images/{a['id']}/thumb")
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"
    assert client.get(f"/api/images/{a['id']}/preview").status_code == 200


def test_reveal_requires_ui_header_and_calls_os(client, lib):
    scan(client, lib)
    image_id = client.get("/api/images").json()["items"][0]["id"]
    assert client.post(f"/api/images/{image_id}/reveal").status_code == 403
    with mock.patch("pixsift.platform_ops.reveal_in_folder") as reveal:
        assert client.post(f"/api/images/{image_id}/reveal", headers=UI).status_code == 200
    reveal.assert_called_once()


def test_rejects_bad_root(client, tmp_path):
    r = client.post("/api/scan", json={"roots": [str(tmp_path / "nope")]}, headers=UI)
    assert r.status_code == 400
