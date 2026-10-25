"""A stuck or failing picture, or an unplugged drive, must never stop the analysis job."""

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import pixsift.pipeline as pl
from pixsift.api import create_app
from pixsift.config import Settings

UI = {"X-PixSift": "1"}


class FakeAnalyzer:
    def __init__(self, hang_on=(), fail_on=()):
        self.hang_on, self.fail_on = hang_on, fail_on

    def analyze(self, path, filename, camera):
        if filename in self.hang_on:
            time.sleep(3)  # longer than the test's timeout: looks stuck
        if filename in self.fail_on:
            raise OSError("decoder error")
        return None  # "nothing found"; recorded as analysed


@pytest.fixture
def lib(tmp_path, monkeypatch):
    for i in range(6):
        Image.new("RGB", (200, 150), (i * 40, 0, 0)).save(tmp_path / f"p{i}.jpg")
    app = create_app(Settings(data_dir=tmp_path / "data", min_file_bytes=10, token="t"))
    app.state.pipeline.models.ensure = lambda cancel=None: None
    with TestClient(app, cookies={"pixsift_token": "t"}) as c:
        c.post("/api/scan", json={"roots": [str(tmp_path)], "analyze": False}, headers=UI).raise_for_status()
        app.state.pipeline.join(30)
        yield c, app, tmp_path


def run_analysis(app, analyzer):
    app.state.pipeline._analyzer = analyzer
    app.state.pipeline.start(None)
    app.state.pipeline.join(30)
    assert not app.state.pipeline.running, "analysis job hung"
    return app.state.pipeline.snapshot()


def pending(app):
    return {r["filename"] for r in app.state.db.query("SELECT filename FROM images WHERE analyzed_at IS NULL")}


def test_a_hanging_picture_is_skipped_and_the_job_finishes(lib, monkeypatch):
    c, app, _ = lib
    monkeypatch.setattr(pl, "ANALYZE_TIMEOUT", 0.5)
    st = run_analysis(app, FakeAnalyzer(hang_on={"p2.jpg"}))
    assert st["state"] == "done" and st["timeouts"] == 1
    assert pending(app) == set()
    err = app.state.db.query_one("SELECT error FROM images WHERE filename='p2.jpg'")["error"]
    assert "timed out" in err


def test_a_failure_while_saving_results_does_not_stop_the_job(lib, monkeypatch):
    c, app, _ = lib
    real = pl.apply_analysis

    def flaky(db, thumbs, row, result):
        if row["filename"] == "p3.jpg":
            raise ValueError("cannot save face crop")
        return real(db, thumbs, row, result)

    monkeypatch.setattr(pl, "apply_analysis", flaky)
    st = run_analysis(app, FakeAnalyzer(fail_on={"p1.jpg"}))
    assert st["state"] == "done" and pending(app) == set()


def test_pictures_on_an_unplugged_drive_wait_for_it(lib):
    c, app, root = lib
    db = app.state.db
    vid = db.execute("INSERT INTO volumes(uid, label, mount, mounted, status) VALUES ('mac:X', 'Ext', ?, 0, 'tracked')",
                     (str(root),)).lastrowid
    db.execute("UPDATE images SET volume_id=? WHERE filename IN ('p0.jpg', 'p1.jpg')", (vid,))
    (root / "p5.jpg").unlink()  # this one vanishes mid-way (e.g. the drive went to sleep)
    run_analysis(app, FakeAnalyzer())
    assert pending(app) == {"p0.jpg", "p1.jpg", "p5.jpg"}  # retried later instead of "analysed with no result"
